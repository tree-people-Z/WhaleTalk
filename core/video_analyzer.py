"""
视频分析器
负责搜索、筛选、分析视频
"""

import asyncio
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
from utils.database import Database
from utils.config_manager import ConfigManager


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

        # 初始化双日记系统
        self.diary = DiarySystem()

        # 初始化画面分析器
        self.frame_analyzer = FrameAnalyzer()
        self.enable_frame_analysis = self.config.get('analysis.enable_frame_analysis', True)
        self.local_transcriber = LocalAudioTranscriber(
            model_name=self.config.get('analysis.local_transcription_model', 'small')
        )

        # 初始化评论管理器（用于自动回复）
        from core.comment_manager import CommentManager
        self.comment_manager = CommentManager(
            bili_api=self.bili,
            ai_client=self.ai,
            database=self.db,
            config=self.config
        )

    async def check_replies(self) -> Dict[str, Any]:
        """单独检查并回复评论，供高频调度使用。"""
        self._raise_if_stopping()
        if not self.config.get('interaction.comment_monitor', False):
            return {'status': 'replies_checked', 'replied': 0}
        replied = await self.comment_manager.check_and_reply()
        return {'status': 'replies_checked', 'replied': replied}

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

        for video in videos[:max_videos]:
            self._raise_if_stopping()
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

                # 收集值得的视频
                if analysis['worthy']:
                    worthy_videos.append({
                        'video': video,
                        'analysis': analysis
                    })

            # 避免请求过快
            await asyncio.sleep(2)

        logger.info(f"分析完成: {len(analyzed_videos)} 个视频, {len(worthy_videos)} 个值得关注")

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
        """搜索视频"""
        keywords = self.config.get('search.keywords', ['Python', 'AI'])
        max_per_keyword = self.config.get('search.max_results_per_keyword', 5)
        order = self.config.get('search.order', 'pubdate')

        all_videos = []
        seen_bvids = set()

        for keyword in keywords:
            try:
                videos = await self.bili.search_videos(
                    keyword=keyword,
                    page=1,
                    order=order
                )

                for video in videos[:max_per_keyword]:
                    if video['bvid'] not in seen_bvids:
                        all_videos.append(video)
                        seen_bvids.add(video['bvid'])

                await asyncio.sleep(1)

            except Exception as e:
                logger.error(f"搜索'{keyword}'失败: {e}")

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

            if not subtitle and self.config.get('analysis.local_transcription_enabled', True):
                if media_urls.get('audio') and self.frame_analyzer.ffmpeg_available:
                    try:
                        with tempfile.TemporaryDirectory(prefix='bili-audio-') as audio_dir:
                            subtitle = await self.local_transcriber.transcribe_url(
                                media_urls['audio'], str(Path(audio_dir) / 'audio.wav'),
                                ffmpeg_path=self.frame_analyzer.ffmpeg_path,
                            )
                            if subtitle:
                                text_evidence_type = '本地语音转写'
                    except Exception as exc:
                        logger.warning(f"本地语音转写失败 {bvid}: {exc}")
                else:
                    logger.warning(f"视频 {bvid} 无法取得音频流或本机缺少ffmpeg")

            if not subtitle and not frame_paths:
                if frame_tempdir:
                    frame_tempdir.cleanup()
                    frame_tempdir = None
                logger.warning(f"视频 {bvid} 缺少字幕、转写和画面证据，仅以标题和评论低置信度分析")

            # 获取热门评论
            comments = await self.bili.get_comments(video['aid'], count=10)
            comment_texts = [c['content'] for c in comments if c['content']]

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

            logger.info(
                f"分析结果: 评分={analysis['score']}, 值得={analysis['worthy']}, "
                f"置信度={analysis.get('confidence', 'medium')}"
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

        # 检查评分是否达标
        min_score = self.config.get('limits.min_score_to_comment', 13)
        if analysis['score'] < min_score:
            logger.info(f"评分不足，跳过评论: {analysis['score']} < {min_score}")
            return False
        if analysis.get('confidence') == 'low':
            logger.info(f"分析置信度低，跳过自动评论: {bvid}")
            return False

        try:
            # 加载人设
            persona = self._load_persona()

            # 获取要@的用户
            mention_threshold = self.config.get('limits.min_score_to_mention_owner', 17)
            should_mention_owner = (
                self.config.get('interaction.mention_owner_on_interesting', False)
                and
                analysis.get('interesting', False)
                and analysis.get('notify_owner', False)
                and analysis.get('score', 0) >= mention_threshold
            )
            mention_user = (
                self.config.get('bilibili.owner_name', '')
                if should_mention_owner else None
            )

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
