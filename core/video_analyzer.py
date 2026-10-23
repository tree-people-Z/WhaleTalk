"""
视频分析器
负责搜索、筛选、分析视频
"""

import asyncio
import random
import re
import threading
import tempfile
from typing import List, Dict, Any, Optional
from datetime import datetime
from pathlib import Path
from loguru import logger

from core.bilibili_api import BilibiliAPI
from core.ai_client import AIClient
from core.diary_system import DiarySystem
from core.frame_analyzer import FrameAnalyzer
from core.audio_transcriber import LocalAudioTranscriber
from core.cloud_transcriber import CloudAudioTranscriber
from utils.database import Database
from utils.config_manager import ConfigManager


# 视频标题/字幕中明确要求“把这个视频 @ 给主人”时，优先遵从这条指令。
_OWNER_DIRECTIVE_PATTERNS = (
    re.compile(r'@\s*[^，。！？\n]{0,12}主人'),
    re.compile(r'艾特[^，。！？\n]{0,12}主人'),
    re.compile(
        r'把[^，。！？\n]{0,12}视频[^，。！？\n]{0,16}(?:@|艾特)[^，。！？\n]{0,12}主人'
    ),
    re.compile(
        r'(?:叫|让|通知|转告|提醒)[^，。！？\n]{0,10}主人[^，。！？\n]{0,10}(?:看|来|知道)'
    ),
)


class VideoAnalyzer:
    """视频分析器"""

    def __init__(
        self,
        bili_api: BilibiliAPI,
        ai_client: AIClient,
        database: Database,
        config: ConfigManager
    ):
        self.bili = bili_api
        self.ai = ai_client
        self.db = database
        self.config = config
        self._stop_requested = threading.Event()
        self._greetings_sent_this_run = 0
        self._interactions_sent_this_run = 0
        self._search_page = 1

        # 初始化双日记系统
        self.diary = DiarySystem()

        # 初始化画面分析器
        self.frame_analyzer = FrameAnalyzer()
        self.enable_frame_analysis = self.config.get('analysis.enable_frame_analysis', True)
        self.local_transcriber = LocalAudioTranscriber(
            model_name=self.config.get('analysis.local_transcription_model', 'medium')
        )

        # 初始化评论管理器（用于自动回复）
        from core.comment_manager import CommentManager
        self.comment_manager = CommentManager(
            bili_api=self.bili,
            ai_client=self.ai,
            database=self.db,
            config=self.config
        )

    def _cloud_transcriber(self) -> CloudAudioTranscriber:
        """Build a cloud transcriber from the current settings."""
        return CloudAudioTranscriber(
            base_url=self.config.get(
                'analysis.cloud_transcription.base_url', 'https://api.openai.com/v1'
            ),
            api_key=self.config.get('analysis.cloud_transcription.api_key', ''),
            model=self.config.get('analysis.cloud_transcription.model', 'whisper-1'),
        )

    @staticmethod
    def _has_owner_directive(*texts: Optional[str]) -> bool:
        """Detect explicit instructions such as '把这个视频@给主人'."""
        combined = ' '.join(text for text in texts if text)
        return any(pattern.search(combined) for pattern in _OWNER_DIRECTIVE_PATTERNS)

    _WHALE_NAME_KEYWORDS = ('鲸鱼娘', '大肥鱼', 'DeepSeek娘', '鲸语娘')
    _WHALE_CONTENT_KEYWORDS = ('大肥鱼', '软乎乎', '女仆')

    @classmethod
    def _looks_like_whale(cls, comment: Dict[str, Any]) -> bool:
        """Heuristically detect comments from another 鲸鱼娘-style bot."""
        name = str(comment.get('user') or '')
        content = str(comment.get('content') or '')
        if any(keyword in name for keyword in cls._WHALE_NAME_KEYWORDS):
            return True
        return (
            '鲸鱼娘' in content
            and any(keyword in content for keyword in cls._WHALE_CONTENT_KEYWORDS)
        )

    async def _find_greeting_candidates(self, comments) -> List[Dict[str, Any]]:
        """Collect a few other-whale comments to greet on this video."""
        if not self.config.get('interaction.greet_other_whales', True):
            return []
        try:
            self_info = await self.bili.get_self_info()
        except Exception:  # noqa: BLE001
            self_info = {}
        if not isinstance(self_info, dict):
            self_info = {}
        self_uid = self_info.get('uid')
        self_name = self_info.get('name') or ''
        owner_name = self.config.get('bilibili.owner_name', '')
        try:
            already_replied = set(self.db.get_replied_comment_ids())
        except Exception:  # noqa: BLE001
            already_replied = set()
        try:
            max_candidates = int(self.config.get('limits.max_greetings_per_video', 2))
        except (TypeError, ValueError):
            max_candidates = 2
        if max_candidates <= 0:
            return []

        candidates = []
        for comment in comments or []:
            rpid = comment.get('rpid')
            if not rpid or rpid in already_replied:
                continue
            if self_uid is not None and comment.get('mid') == self_uid:
                continue
            user = comment.get('user') or ''
            if self_name and user == self_name:
                continue
            if owner_name and user == owner_name:
                continue
            if not self._looks_like_whale(comment):
                continue
            candidates.append({
                'rpid': rpid,
                'user': user,
                'content': comment.get('content') or '',
                'root': comment.get('root') or rpid,
                'parent': comment.get('parent') or rpid,
            })
            if len(candidates) >= max_candidates:
                break
        if candidates:
            logger.info(f"发现 {len(candidates)} 个其他鲸鱼娘评论，可打招呼")
        return candidates

    async def _greet_other_whales(
        self, video: Dict[str, Any], analysis: Dict[str, Any]
    ) -> int:
        """Reply briefly to other 鲸鱼娘 comments, with per-run limits."""
        if not self.config.get('interaction.greet_other_whales', True):
            return 0
        if not self.config.get('interaction.auto_comment', False):
            return 0
        candidates = analysis.get('greeting_candidates') or []
        if not candidates:
            return 0
        try:
            per_run = int(self.config.get('limits.max_greetings_per_run', 5))
        except (TypeError, ValueError):
            per_run = 5
        remaining = max(0, per_run - self._greetings_sent_this_run)
        if remaining <= 0:
            return 0

        persona = self._load_persona()
        sent = 0
        for target in candidates[:remaining]:
            try:
                reply = await self.ai.generate_reply(
                    original_comment=(
                        f"另一位鲸鱼娘/同好说：{target.get('content', '')}"
                    ),
                    video_context=f"视频: {video.get('title', '')}",
                    persona=persona,
                )
                if not reply:
                    continue
                success = await self.bili.post_comment(
                    aid=video['aid'],
                    text=reply,
                    root_rpid=target.get('root') or target.get('rpid'),
                    parent_rpid=target.get('rpid'),
                )
                if success:
                    self.db.add_comment_record(
                        bvid=video.get('bvid', ''),
                        aid=video.get('aid'),
                        content=reply,
                        comment_type='reply',
                        success=True,
                        rpid=getattr(self.bili, 'last_comment_rpid', None),
                        parent_rpid=target.get('rpid'),
                        target_user=target.get('user') or '',
                    )
                    self._greetings_sent_this_run += 1
                    sent += 1
                    logger.info(f"👋 已向其他鲸鱼娘打招呼: {target.get('user')}")
                await asyncio.sleep(2)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"向其他鲸鱼娘打招呼失败: {exc}")
        return sent

    @staticmethod
    def _looks_like_reply_invitation(content: str) -> bool:
        """Detect comments that invite a reply, e.g. '鱼会回复吗'."""
        text = (content or '').strip()
        if not text or len(text) > 200:
            return False
        bot_terms = (
            '鲸鱼娘', '大肥鱼', '鱼', '回复', '回我', '理我',
            '在吗', '冒泡', '机器人', 'AI娘', '主播',
        )
        if not any(term in text for term in bot_terms):
            return False
        asks = any(mark in text for mark in ('?', '？', '吗', '么', '呢', '嘛'))
        return asks or '回复' in text

    async def _find_reply_invitations(self, comments) -> List[Dict[str, Any]]:
        """Collect a few top-level comments that invite a reply."""
        if not self.config.get('interaction.reply_interesting_comments', True):
            return []
        only_owner = bool(self.config.get('interaction.reply_only_owner', False))
        reply_to_others = self.config.get('interaction.reply_to_others', True)
        owner_name = self.config.get('bilibili.owner_name', '')
        if only_owner and not owner_name:
            return []
        if not only_owner and not reply_to_others:
            return []
        try:
            self_info = await self.bili.get_self_info()
        except Exception:  # noqa: BLE001
            self_info = {}
        if not isinstance(self_info, dict):
            self_info = {}
        self_uid = self_info.get('uid')
        self_name = self_info.get('name') or ''
        try:
            already_replied = set(self.db.get_replied_comment_ids())
        except Exception:  # noqa: BLE001
            already_replied = set()
        try:
            max_candidates = int(
                self.config.get('limits.max_interactions_per_video', 1)
            )
        except (TypeError, ValueError):
            max_candidates = 1
        if max_candidates <= 0:
            return []

        candidates = []
        for comment in comments or []:
            rpid = comment.get('rpid')
            if not rpid or rpid in already_replied:
                continue
            # 只处理顶层评论；楼中楼回复由回复检查处理。
            if comment.get('root') not in (0, None):
                continue
            if self_uid is not None and comment.get('mid') == self_uid:
                continue
            user = comment.get('user') or ''
            if self_name and user == self_name:
                continue
            if only_owner and user != owner_name:
                continue
            content = comment.get('content') or ''
            if not self._looks_like_reply_invitation(content):
                continue
            candidates.append({
                'rpid': rpid,
                'user': user,
                'content': content,
                'root': rpid,
                'parent': rpid,
            })
            if len(candidates) >= max_candidates:
                break
        if candidates:
            logger.info(f"发现 {len(candidates)} 条可互动评论，准备回复")
        return candidates

    async def _reply_to_invitations(
        self, video: Dict[str, Any], analysis: Dict[str, Any]
    ) -> int:
        """Reply to viewer comments such as '鱼会回复吗', with per-run limits."""
        if not self.config.get('interaction.reply_interesting_comments', True):
            return 0
        if not self.config.get('interaction.auto_comment', False):
            return 0
        if self.bili.is_blocked():
            return 0
        candidates = analysis.get('reply_invitations') or []
        if not candidates:
            return 0
        try:
            per_run = int(self.config.get('limits.max_interactions_per_run', 3))
        except (TypeError, ValueError):
            per_run = 3
        remaining = max(0, per_run - self._interactions_sent_this_run)
        if remaining <= 0:
            return 0

        persona = self._load_persona()
        sent = 0
        for target in candidates[:remaining]:
            try:
                reply = await self.ai.generate_reply(
                    original_comment=target.get('content', ''),
                    video_context=f"视频: {video.get('title', '')}",
                    persona=persona,
                )
                if not reply:
                    continue
                success = await self.bili.post_comment(
                    aid=video['aid'],
                    text=reply,
                    root_rpid=target.get('rpid'),
                    parent_rpid=target.get('rpid'),
                )
                if success:
                    self.db.add_comment_record(
                        bvid=video.get('bvid', ''),
                        aid=video.get('aid'),
                        content=reply,
                        comment_type='reply',
                        success=True,
                        rpid=getattr(self.bili, 'last_comment_rpid', None),
                        parent_rpid=target.get('rpid'),
                        target_user=target.get('user') or '',
                    )
                    self._interactions_sent_this_run += 1
                    sent += 1
                    logger.info(f"💬 已回复评论互动: {target.get('user')}")
                await asyncio.sleep(2)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"回复评论互动失败: {exc}")
        return sent

    async def check_replies(self) -> Dict[str, Any]:
        """单独检查并回复评论，供高频调度使用。"""
        self._raise_if_stopping()
        if not self.config.get('interaction.comment_monitor', False):
            return {'status': 'replies_checked', 'replied': 0, 'mentions': []}
        if self.bili.is_blocked():
            logger.warning("B站风控冷却中，跳过回复检查")
            return {'status': 'replies_checked', 'replied': 0, 'mentions': []}
        result = await self.comment_manager.check_and_reply()
        return {
            'status': 'replies_checked',
            'replied': result.get('replied', 0),
            'mentions': result.get('mentions', []),
        }

    def request_stop(self):
        """请求在当前网络操作结束后停止本轮分析。"""
        self._stop_requested.set()

    def _raise_if_stopping(self):
        if self._stop_requested.is_set():
            raise asyncio.CancelledError()

    async def run_analysis_cycle(self) -> Dict[str, Any]:
        """
        运行一轮完整的分析周期

        Returns:
            运行结果统计
        """
        logger.info("=" * 60)
        logger.info("开始新一轮视频分析")
        logger.info("=" * 60)
        self._greetings_sent_this_run = 0
        self._interactions_sent_this_run = 0
        self._raise_if_stopping()

        # 检查今日配额
        quota = self.db.get_today_quota()
        max_comments = self.config.get('limits.max_comments_per_day', 999)

        if quota.comments_sent >= max_comments:
            logger.warning(f"今日评论配额已用完 ({quota.comments_sent}/{max_comments})")
            return {
                'status': 'quota_exhausted',
                'videos_found': 0,
                'videos_analyzed': 0,
                'comments_sent': 0
            }

        if self.bili.is_blocked():
            logger.warning("B站风控冷却中，跳过本轮分析")
            return {
                'status': 'risk_control',
                'videos_found': 0,
                'videos_analyzed': 0,
                'comments_sent': 0
            }

        # 1. 搜索视频
        videos = await self._search_videos()
        logger.info(f"搜索到 {len(videos)} 个视频")

        if not videos:
            return {
                'status': 'no_videos_found',
                'videos_found': 0,
                'videos_analyzed': 0,
                'comments_sent': 0
            }

        # 2. 筛选和分析
        analyzed_videos = []
        worthy_videos = []

        max_videos = self.config.get('limits.max_videos_per_run', 10)
        min_comment_score = self.config.get('limits.min_score_to_comment', 10)

        for video in videos[:max_videos]:
            self._raise_if_stopping()
            # 持续巡视时跳过最近分析过的视频，避免反复分析同一批内容。
            if self.db.is_video_analyzed_recently(
                video['bvid'],
                hours=self.config.get('limits.skip_analyzed_within_hours', 2),
            ):
                logger.info(f"跳过最近已分析的视频: {video['bvid']}")
                continue
            # 检查是否最近评论过
            if self.db.check_video_commented_recently(
                video['bvid'],
                days=self.config.get('limits.same_video_cooldown_days', 7)
            ):
                logger.info(f"跳过最近已评论的视频: {video['bvid']}")
                continue

            # 分析视频
            analysis = await self._analyze_video(video)

            if analysis:
                analyzed_videos.append({
                    'video': video,
                    'analysis': analysis
                })

                # 保存到数据库
                self.db.add_video_record(
                    bvid=video['bvid'],
                    video_info=video,
                    analysis=analysis
                )
                self.db.increment_videos()

                await self._reply_to_invitations(video, analysis)

                # 评论候选由「评论最低评分」设置控制；明确 @主人 指令的视频不参与再筛选。
                if analysis['score'] >= min_comment_score or analysis.get('owner_directive'):
                    worthy_videos.append({
                        'video': video,
                        'analysis': analysis
                    })

            # 避免请求过快
            await asyncio.sleep(2)

        logger.info(f"分析完成: {len(analyzed_videos)} 个视频, {len(worthy_videos)} 个达到评论评分门槛")

        # 3. 从值得的视频中挑选评论
        comments_sent = 0
        remaining_quota = max_comments - quota.comments_sent

        if worthy_videos and remaining_quota > 0:
            # 按评分排序
            worthy_videos.sort(key=lambda x: x['analysis']['score'], reverse=True)

            # 发送评论
            for item in worthy_videos[:remaining_quota]:
                self._raise_if_stopping()
                bvid = item['video']['bvid']
                title = item['video']['title']
                video_url = f"https://www.bilibili.com/video/{bvid}"

                success = await self._post_comment_for_video(
                    item['video'],
                    item['analysis']
                )

                if success:
                    comments_sent += 1
                    self.db.increment_comments()
                    logger.info(f"✅ 评论成功: {title}")
                    logger.info(f"   视频链接: {video_url}")

                await asyncio.sleep(3)

        # 4. 更新运行统计
        self.db.increment_runs()

        # 5. 检查并回复评论和私信
        if (self.config.get('interaction.comment_monitor', False)
                and self.config.get('interaction.auto_reply', True)):
            logger.info("=" * 60)
            logger.info("检查评论回复和私信")
            logger.info("=" * 60)

            try:
                # 检查评论回复
                mentions = await self.comment_manager.check_mentions()
                logger.info(f"发现 {len(mentions)} 条新回复")

                for mention in mentions:
                    self._raise_if_stopping()
                    success = await self.comment_manager.reply_to_mention(mention)
                    if success:
                        logger.info(f"✅ 已回复: {mention.get('user')}")
                    await asyncio.sleep(3)  # 避免频繁回复

            except Exception as e:
                logger.error(f"自动回复失败: {e}")

        result = {
            'status': 'success',
            'videos_found': len(videos),
            'videos_analyzed': len(analyzed_videos),
            'worthy_count': len(worthy_videos),
            'comments_sent': comments_sent,
            'timestamp': datetime.now().isoformat()
        }

        logger.info(f"本轮结束: {result}")
        return result

    async def _search_videos(self) -> List[Dict[str, Any]]:
        """搜索视频，按关键词轮询交错，避免后面的关键词被截断。"""
        keywords = list(self.config.get('search.keywords', ['Python', 'AI']))
        max_per_keyword = self.config.get('search.max_results_per_keyword', 5)
        order = self.config.get('search.order', 'pubdate')

        # 每轮随机关键词顺序，避免总是同一个关键词优先。
        random.shuffle(keywords)
        page = getattr(self, '_search_page', 1)
        pools: List[List[Dict[str, Any]]] = []
        for keyword in keywords:
            try:
                videos = await self.bili.search_videos(
                    keyword=keyword,
                    page=page,
                    order=order
                )

                pool = []
                pool_seen = set()
                for video in videos[:max_per_keyword]:
                    bvid = video.get('bvid')
                    if bvid and bvid not in pool_seen:
                        pool_seen.add(bvid)
                        pool.append(video)
                if pool:
                    pools.append(pool)

                await asyncio.sleep(1)

            except Exception as e:
                logger.error(f"搜索'{keyword}'失败: {e}")

        # 轮询：各关键词轮流各取一条，保证名额公平分配。
        all_videos: List[Dict[str, Any]] = []
        seen_bvids = set()
        max_pool_length = max((len(pool) for pool in pools), default=0)
        for index in range(max_pool_length):
            for pool in pools:
                if index >= len(pool):
                    continue
                video = pool[index]
                bvid = video.get('bvid')
                if bvid and bvid not in seen_bvids:
                    seen_bvids.add(bvid)
                    all_videos.append(video)

        # 下一轮换搜索页，避免每轮都重复分析同一批视频。
        self._search_page = page % 3 + 1
        return all_videos

    async def _analyze_video(self, video: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """分析单个视频"""
        bvid = video['bvid']
        title = video['title']

        logger.info(f"分析视频: {title} ({bvid})")

        frame_tempdir = None
        try:
            # 字幕优先；无字幕时用本地语音识别补齐文本证据。
            subtitle = await self.bili.get_subtitle(bvid)
            text_evidence_type = 'B站字幕'
            media_urls = {'audio': None, 'video': None}
            frame_paths = []
            if self.enable_frame_analysis or not subtitle:
                media_urls = await self.bili.get_media_urls(bvid)

            if self.enable_frame_analysis and media_urls.get('video'):
                frame_tempdir = tempfile.TemporaryDirectory(prefix='bili-frames-')
                frame_paths = await self.frame_analyzer.extract_frames(
                    media_urls['video'], frame_tempdir.name, count=3, duration=video.get('duration')
                )

            transcription_mode = self.config.get('analysis.transcription_mode', 'off')
            if not subtitle and transcription_mode in ('local', 'cloud'):
                if media_urls.get('audio') and self.frame_analyzer.ffmpeg_available:
                    try:
                        with tempfile.TemporaryDirectory(prefix='bili-audio-') as audio_dir:
                            if transcription_mode == 'cloud':
                                subtitle = await self._cloud_transcriber().transcribe_url(
                                    media_urls['audio'],
                                    str(Path(audio_dir) / 'audio.mp3'),
                                    ffmpeg_path=self.frame_analyzer.ffmpeg_path,
                                )
                                if subtitle:
                                    text_evidence_type = '云端语音转写'
                            else:
                                subtitle = await self.local_transcriber.transcribe_url(
                                    media_urls['audio'],
                                    str(Path(audio_dir) / 'audio.wav'),
                                    ffmpeg_path=self.frame_analyzer.ffmpeg_path,
                                )
                                if subtitle:
                                    text_evidence_type = '本地语音转写'
                    except Exception as exc:
                        logger.warning(f"语音转写失败 {bvid}: {exc}")
                else:
                    logger.warning(f"视频 {bvid} 无法取得音频流或本机缺少ffmpeg")

            if not subtitle and not frame_paths:
                if frame_tempdir:
                    frame_tempdir.cleanup()
                    frame_tempdir = None
                logger.warning(f"视频 {bvid} 缺少字幕、转写和画面证据，仅以标题和评论低置信度分析")

            # 获取热门评论
            comments = await self.bili.get_comments(video['aid'], count=15)
            comment_texts = [c['content'] for c in comments if c['content']]
            greeting_candidates = await self._find_greeting_candidates(comments)
            reply_invitations = await self._find_reply_invitations(comments)

            # 加载人设
            persona = self._load_persona()

            # AI分析
            analysis = await self.ai.analyze_video(
                title=title,
                subtitle=subtitle,
                comments=comment_texts,
                persona=persona,
                video_metrics={
                    'play': video.get('play'),
                    'comment_count': video.get('comment_count'),
                    'like': video.get('like'),
                    'favorites': video.get('favorites'),
                    'duration': video.get('duration'),
                    'author': video.get('author'),
                },
                image_paths=frame_paths,
                text_evidence_type=text_evidence_type,
            )
            if frame_tempdir:
                frame_tempdir.cleanup()
                frame_tempdir = None

            if not analysis or analysis.get('error'):
                logger.warning(f"AI分析未完成，跳过记录: {bvid}")
                return None

            # Visual-only judgments are useful for discovery, but are not enough
            # evidence for an autonomous public comment.
            if not subtitle:
                analysis['confidence'] = 'low'

            # 标题/字幕里明确要求 @主人 的视频优先遵从指令。
            analysis['owner_directive'] = self._has_owner_directive(
                title, subtitle or ''
            )
            # “值得”改为表示“达到评论门槛或含明确指令”，与评论行为保持一致。
            min_comment_score = self.config.get('limits.min_score_to_comment', 10)
            analysis['worthy'] = bool(
                analysis.get('score', 0) >= min_comment_score
                or analysis['owner_directive']
            )
            analysis['greeting_candidates'] = greeting_candidates
            analysis['reply_invitations'] = reply_invitations

            logger.info(
                f"分析结果: 评分={analysis['score']}, 值得={analysis['worthy']}, "
                f"置信度={analysis.get('confidence', 'medium')}"
                + ("，含@主人指令" if analysis['owner_directive'] else "")
            )
            return analysis

        except Exception as e:
            if frame_tempdir:
                frame_tempdir.cleanup()
            logger.error(f"分析视频失败 {bvid}: {e}")
            return None

    async def _post_comment_for_video(
        self,
        video: Dict[str, Any],
        analysis: Dict[str, Any]
    ) -> bool:
        """为视频发送评论"""
        bvid = video['bvid']
        aid = video['aid']
        title = video['title']

        # 检查是否启用自动评论
        if not self.config.get('interaction.auto_comment', False):
            logger.info(f"自动评论未启用，跳过评论: {bvid}")
            return False

        # 检查评分是否达标；明确要求 @主人 的视频按指令执行，不再参与评分筛选。
        directive = bool(analysis.get('owner_directive'))
        min_score = self.config.get('limits.min_score_to_comment', 10)
        if analysis['score'] < min_score and not directive:
            logger.info(f"评分不足，跳过评论: {analysis['score']} < {min_score}")
            return False
        if analysis.get('confidence') == 'low' and not directive:
            logger.info(f"分析置信度低，跳过自动评论: {bvid}")
            return False
        if directive:
            logger.info(f"视频含明确 @主人 指令，按指令评论: {bvid}")

        try:
            # 加载人设
            persona = self._load_persona()

            # 获取要@的用户；指令性视频跳过评分门槛，但仍尊重 @主人 开关。
            mention_threshold = self.config.get('limits.min_score_to_mention_owner', 13)
            owner_name = self.config.get('bilibili.owner_name', '')
            mention_enabled = self.config.get(
                'interaction.mention_owner_on_interesting', False
            )
            should_mention_owner = (
                mention_enabled
                and bool(owner_name)
                and (
                    directive
                    or analysis.get('score', 0) >= mention_threshold
                )
            )
            mention_user = owner_name if should_mention_owner else None
            if mention_user:
                reason = "含明确 @主人 指令" if directive else (
                    f"评分 {analysis.get('score', 0)} 达到 @主人 阈值"
                )
                logger.info(f"{reason}，评论将提及 {mention_user}")
            elif directive and not mention_enabled:
                logger.info("视频含 @主人 指令，但“在评论中 @我”开关关闭，不提及主人")

            # 生成评论
            comment_text = await self.ai.generate_comment(
                video_title=title,
                video_content=analysis['summary'],
                persona=persona,
                mention_user=mention_user or None
            )

            if not comment_text:
                logger.error("生成评论失败")
                return False

            logger.info(f"准备发送评论: {comment_text}")

            # 发送评论
            success = await self.bili.post_comment(aid, comment_text)
            comment_rpid = getattr(self.bili, 'last_comment_rpid', None)

            # 记录到数据库
            self.db.add_comment_record(
                bvid=bvid,
                aid=aid,
                content=comment_text,
                comment_type='post',
                success=success,
                rpid=comment_rpid
            )

            if success:
                self.db.mark_commented(bvid, comment_text, comment_rpid)
                logger.info(f"✅ 评论成功: {title}")
                await self._greet_other_whales(video, analysis)
            else:
                logger.error(f"❌ 评论失败: {title}")

            return success

        except Exception as e:
            logger.error(f"发送评论异常 {bvid}: {e}")
            return False

    def _load_persona(self) -> str:
        """加载角色人设"""
        if not self.config.get('persona.enabled', True):
            return ""

        persona_file = self.config.get('persona.persona_file', 'data/persona.md')
        persona_path = Path(persona_file)

        if not persona_path.exists():
            # 返回基本人设
            name = self.config.get('persona.name', 'AI助手')
            return f"你是 {name}，一个友好的AI助手。"

        try:
            with open(persona_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return content[:3000]  # 限制长度
        except Exception as e:
            logger.warning(f"加载人设文件失败: {e}")
            return ""


# 同步包装器
class VideoAnalyzerSync:
    """视频分析器同步版本。"""

    def __init__(self, *args, **kwargs):
        self.analyzer = VideoAnalyzer(*args, **kwargs)
        self.loop = asyncio.new_event_loop()

    def run_analysis_cycle(self):
        """运行分析周期（同步）。"""
        return self.loop.run_until_complete(self.analyzer.run_analysis_cycle())

    def close(self):
        """释放事件循环资源。"""
        if not self.loop.is_closed():
            self.loop.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
