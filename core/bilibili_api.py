"""
B站API封装模块
提供登录、搜索、字幕、评论等核心功能
"""

import asyncio
import re
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

from bilibili_api import search, video, user
from bilibili_api import Credential
from bilibili_api.search import SearchObjectType, OrderVideo
from core.bilibili_auth import BiliAuthMixin
from core.bilibili_guard import BiliGuardMixin
from core.bilibili_dm import BiliDMMixin
from core.bilibili_comment import BiliCommentMixin
from core.bilibili_interact import BiliInteractMixin
from utils.simple_cache import cached_video
from loguru import logger


class BilibiliAPI(
    BiliAuthMixin, BiliGuardMixin, BiliDMMixin,
    BiliCommentMixin, BiliInteractMixin,
):
    """B站API封装类"""

    def __init__(self, credential_path: Path = None):
        """
        初始化B站API

        Args:
            credential_path: 凭证文件路径
        """
        self.credential_path = credential_path or Path("data/cookies.json")
        self.credential: Optional[Credential] = None
        self._load_credential()

        # 自动 buvid 保持开启；bili_ticket 在当前 B 站接口下会返回缺少 data
        # 的响应并导致所有 API 调用 KeyError('data')，因此显式关闭。
        try:
            from bilibili_api import request_settings
            request_settings.set_enable_auto_buvid(True)
            request_settings.set_enable_bili_ticket(False)
        except (ImportError, AttributeError) as exc:
            logger.debug(f"配置 B 站请求参数失败: {exc}")

        # 上游库大版本会改接口，提前告警而不是等到扫码时才报错。
        try:
            from bilibili_api import login_v2
            if not hasattr(login_v2.QrCodeLogin, 'check_state'):
                logger.warning(
                    'bilibili-api 版本与代码不匹配（缺少 login_v2.check_state），'
                    '请按 requirements.txt 重新安装依赖'
                )
        except ImportError as exc:
            logger.warning(f'bilibili-api 登录模块不可用: {exc}')

        # 风控状态
        self.blocked_until: Optional[datetime] = None
        # 评论发送上限（B站 12014）状态：冷却到次日 00:05
        self.posting_blocked_until: Optional[datetime] = None
        self.posting_block_reason = ''
        # 评论请求限速，避免短时间内大量请求触发 B 站风控
        self._comment_min_interval = 2.0
        self._last_comment_request_at = 0.0
        self._comment_request_lock: Optional[asyncio.Lock] = None
        # 只缓存“分析用”的评论页，回复检查必须拿最新数据
        self._comments_cache: Dict[tuple, tuple] = {}
        # 评论区关闭（12002）的短期缓存，避免反复请求
        self._closed_comment_aids: Dict[int, datetime] = {}
        # 12014 冷却状态持久化，重启后继续暂停
        self._posting_state_path = self.credential_path.parent / 'posting_blocked.json'
        self._load_posting_state()
        # 当前登录账号（用于过滤自己发出的评论，避免自问自答）
        self._self_info: Optional[Dict[str, Any]] = None
        self._own_videos_cache: Optional[tuple] = None

    async def get_own_videos(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取当前账号最近投稿的视频，用于回复自己视频下的评论。"""
        cache = getattr(self, '_own_videos_cache', None)
        if cache and (datetime.now() - cache[0]).total_seconds() < 300:
            return list(cache[1])
        info = await self.get_self_info()
        uid = info.get('uid')
        if not uid:
            return []
        videos = await self.get_user_videos(uid, limit)
        self._own_videos_cache = (datetime.now(), videos)
        return videos








    async def search_videos(
        self,
        keyword: str,
        page: int = 1,
        order: str = "pubdate"  # pubdate=最新发布, click=最多播放
    ) -> List[Dict[str, Any]]:
        """
        搜索视频

        Args:
            keyword: 搜索关键词
            page: 页码
            order: 排序方式 ("pubdate"或"click")

        Returns:
            视频列表
        """
        if self.is_blocked():
            logger.warning("当前处于风控状态，跳过搜索")
            return []

        try:
            # 将界面和配置中的排序值原样映射到 bilibili-api 枚举。
            order_types = {
                "totalrank": OrderVideo.TOTALRANK,
                "pubdate": OrderVideo.PUBDATE,
                "click": OrderVideo.CLICK,
                "dm": OrderVideo.DM,
                "stow": OrderVideo.STOW,
                "scores": OrderVideo.SCORES,
            }
            order_type = order_types.get(str(order).lower(), OrderVideo.TOTALRANK)

            result = await search.search_by_type(
                keyword=keyword,
                search_type=SearchObjectType.VIDEO,
                order_type=order_type,
                page=page
            )

            videos = []
            for item in result.get('result', []):
                bvid = item.get('bvid')
                aid = item.get('aid')
                if not isinstance(bvid, str) or not re.fullmatch(r'BV[0-9A-Za-z]{10}', bvid):
                    logger.debug(f"跳过搜索结果：BV号无效 ({bvid!r})")
                    continue
                if not aid:
                    logger.debug(f"跳过搜索结果：缺少aid ({bvid})")
                    continue
                # 搜索结果标题包含用于网页高亮的 HTML 标签。
                from html import unescape
                title = unescape(item.get('title') or '')
                title = re.sub(r'<[^>]*>', '', title)
                videos.append({
                    'bvid': bvid,
                    'aid': aid,
                    'title': title,
                    'author': item.get('author'),
                    'duration': item.get('duration'),
                    'play': item.get('play'),
                    'comment_count': item.get('video_review', item.get('review')),
                    'like': item.get('like'),
                    'favorites': item.get('favorites'),
                    'pubdate': item.get('pubdate'),
                    'description': item.get('description', '')
                })

            logger.info(f"搜索'{keyword}'找到 {len(videos)} 个视频")
            return videos

        except Exception as e:
            logger.error(f"搜索视频失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            if "412" in str(e) or "风控" in str(e):
                self.set_blocked(30)
            return []

    async def get_user_videos(self, uid: int, limit: int = 5) -> List[Dict[str, Any]]:
        """获取指定用户的最近投稿视频。"""
        if not uid:
            return []
        try:
            data = await user.User(int(uid), credential=self.credential).get_videos(
                pn=1, ps=max(1, min(int(limit), 30))
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"获取用户 {uid} 投稿视频失败: {exc}")
            return []
        payload = data.get('list') if isinstance(data, dict) else None
        items = (payload or {}).get('vlist') if isinstance(payload, dict) else None
        if not items and isinstance(data, dict):
            items = data.get('vlist') or []
        videos = []
        for item in items or []:
            bvid = item.get('bvid')
            aid = item.get('aid')
            if bvid and aid:
                videos.append({
                    'bvid': bvid,
                    'aid': aid,
                    'title': item.get('title') or bvid,
                })
        return videos

    async def resolve_requested_video(
        self, text: str, commenter_mid: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """解析评论里“看看我的视频/这个视频”的请求，返回可读的视频资料。"""
        if not text:
            return None
        bvid = None
        bv_match = re.search(r'(BV[0-9A-Za-z]{10})', text)
        av_match = re.search(r'av(\d+)', text, re.I)
        b23_match = re.search(r'https?://b23\.tv/\S+', text, re.I)

        if b23_match:
            try:
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        b23_match.group(0),
                        allow_redirects=True,
                        headers={'User-Agent': 'Mozilla/5.0'},
                    ) as response:
                        final_url = str(response.url)
                resolved = re.search(r'(BV[0-9A-Za-z]{10})', final_url)
                if resolved:
                    bvid = resolved.group(1)
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"解析 b23 短链失败: {exc}")

        if not bvid and bv_match:
            bvid = bv_match.group(1)
        if not bvid and av_match:
            try:
                info = await video.Video(
                    aid=int(av_match.group(1)), credential=self.credential
                ).get_info()
                bvid = info.get('bvid')
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"解析 av 号失败: {exc}")

        wants_my_video = bool(re.search(
            r'(看|瞧|瞅).{0,8}(我|俺).{0,6}(视频|投稿|作品)|'
            r'我(的|发的|做的|拍的).{0,4}(视频|投稿|作品)',
            text,
        ))
        if not bvid and wants_my_video and commenter_mid:
            videos = await self.get_user_videos(commenter_mid, limit=3)
            if videos:
                bvid = videos[0].get('bvid')

        if not bvid:
            return None
        info = await self.get_video_info(bvid)
        if not info:
            return None
        subtitle = await self.get_subtitle(bvid) or ''
        subtitle = re.sub(r'\s+', ' ', subtitle).strip()[:1200]
        return {
            'bvid': bvid,
            'aid': info.get('aid'),
            'title': info.get('title') or bvid,
            'desc': (info.get('desc') or '').strip()[:600],
            'owner': info.get('owner') or '',
            'owner_mid': info.get('owner_mid'),
            'duration': info.get('duration') or 0,
            'url': f'https://www.bilibili.com/video/{bvid}',
            'subtitle': subtitle,
            'requested_by': 'commenter_upload' if wants_my_video else 'explicit_link',
        }

    @cached_video
    async def get_video_info(self, bvid: str) -> Optional[Dict[str, Any]]:
        """获取视频详细信息（带缓存）"""
        last_error = None
        for attempt in range(2):
            try:
                v = video.Video(bvid=bvid, credential=self.credential)
                info = await v.get_info()

                return {
                    'bvid': bvid,
                    'aid': info.get('aid'),
                    'title': info.get('title'),
                    'desc': info.get('desc'),
                    'duration': info.get('duration'),
                    'owner': info.get('owner', {}).get('name'),
                    'owner_mid': info.get('owner', {}).get('mid'),
                    'pubdate': info.get('pubdate'),
                    'stat': info.get('stat', {})
                }
            except Exception as e:  # noqa: BLE001
                last_error = e
                # -404/-403/-400 是确定的“视频不存在/无权访问”，
                # 重试只会多打一次接口，还会把日志刷成 ERROR。
                if getattr(e, 'code', None) in (-404, -403, -400):
                    break
                if attempt == 0:
                    await asyncio.sleep(0.5)
                    continue
        if getattr(last_error, 'code', None) in (-404, -403, -400):
            logger.warning(f"视频不存在或无法访问 {bvid}: {last_error}")
        else:
            logger.error(f"获取视频信息失败 {bvid}: {last_error}")
        return None

    async def get_videos_info_batch(
        self, bvids: List[str], max_concurrent: int = 5
    ) -> Dict[str, Optional[Dict[str, Any]]]:
        """批量获取视频信息。

        Args:
            bvids: BV 号列表（自动去重）
            max_concurrent: 最大并发数，限制在 1-10

        Returns:
            {bvid: 视频信息或 None}
        """
        unique = []
        seen = set()
        for item in bvids or []:
            bvid = str(item or '').strip()
            if bvid and bvid not in seen:
                seen.add(bvid)
                unique.append(bvid)
        if not unique:
            return {}
        try:
            limit = max(1, min(int(max_concurrent or 5), 10))
        except (TypeError, ValueError):
            limit = 5
        semaphore = asyncio.Semaphore(limit)

        async def fetch_one(bvid: str):
            async with semaphore:
                try:
                    return bvid, await self.get_video_info(bvid)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(f'批量获取视频失败 {bvid}: {exc}')
                    return bvid, None

        pairs = await asyncio.gather(*(fetch_one(bvid) for bvid in unique))
        return {bvid: info for bvid, info in pairs}

    async def get_video_info_by_aid(self, aid: int) -> Optional[Dict[str, Any]]:
        """通过 aid 读取视频信息；自由 Agent 发评论时只有 aid。"""
        try:
            v = video.Video(aid=int(aid), credential=self.credential)
            info = await v.get_info()
            return {
                'bvid': info.get('bvid') or '',
                'aid': info.get('aid') or int(aid),
                'title': info.get('title') or '',
                'owner': info.get('owner', {}).get('name') or '',
                'owner_mid': info.get('owner', {}).get('mid'),
                'pubdate': info.get('pubdate'),
            }
        except Exception as e:  # noqa: BLE001
            logger.warning(f"通过 aid 获取视频信息失败 {aid}: {e}")
            return None

    async def get_subtitle(self, bvid: str, cid: int = None) -> Optional[str]:
        """
        获取视频字幕

        Args:
            bvid: 视频BV号
            cid: 视频分P的cid（如果为None，自动获取第一个分P）

        Returns:
            字幕文本（合并后的纯文本）
        """
        try:
            v = video.Video(bvid=bvid, credential=self.credential)

            # 如果没有cid，先获取视频信息得到cid
            if cid is None:
                info = await v.get_info()
                cid = info.get('cid')

            if not cid:
                logger.warning(f"无法获取视频 {bvid} 的cid")
                return None

            # 获取字幕信息
            subtitle_info = await v.get_subtitle(cid=cid)

            if not subtitle_info or 'subtitles' not in subtitle_info:
                return None

            # 优先获取中文字幕
            subtitle_list = subtitle_info['subtitles']
            zh_subtitle = None

            for sub in subtitle_list:
                if 'zh' in sub.get('lan', '').lower():
                    zh_subtitle = sub
                    break

            if not zh_subtitle and subtitle_list:
                zh_subtitle = subtitle_list[0]

            if not zh_subtitle:
                return None

            # 下载字幕内容
            subtitle_url = zh_subtitle.get('subtitle_url')
            if subtitle_url.startswith('//'):
                subtitle_url = 'https:' + subtitle_url

            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(subtitle_url) as resp:
                    subtitle_data = await resp.json()

            # 合并字幕文本
            text_parts = []
            for item in subtitle_data.get('body', []):
                text_parts.append(item.get('content', ''))

            full_text = ' '.join(text_parts)
            logger.info(f"获取字幕成功 {bvid}, 长度: {len(full_text)}")
            return full_text

        except Exception as e:
            logger.warning(f"获取字幕失败 {bvid}: {e}")
            return None

    async def get_media_urls(self, bvid: str) -> Dict[str, Optional[str]]:
        """Get short-lived Bilibili audio/video stream URLs for local processing."""
        try:
            v = video.Video(bvid=bvid, credential=self.credential)
            info = await v.get_info()
            cid = info.get('cid')
            if not cid:
                return {'audio': None, 'video': None}
            data = await v.get_download_url(cid=cid)
            dash = data.get('dash') or {}
            audio_tracks = dash.get('audio') or []
            video_tracks = dash.get('video') or []

            def stream_url(track):
                return track.get('baseUrl') or track.get('base_url') or track.get('url')

            def pick_track(tracks):
                """Prefer AVC and a mirror host, then the lowest bandwidth.

                Frame/audio extraction only needs a small, decodable stream; the
                first DASH entry is often the 1080p+ rendition and can make a
                one-frame ffmpeg seek download far more data than necessary.
                """
                if not tracks:
                    return None
                def score(track):
                    url = stream_url(track) or ''
                    codec = str(track.get('codecs') or '')
                    return (
                        0 if codec.startswith('avc1') else 1,
                        0 if 'upos' in url else 1,
                        int(track.get('bandwidth') or 0),
                    )
                return min(tracks, key=score)

            audio_track = pick_track(audio_tracks)
            video_track = pick_track(video_tracks)
            audio_url = stream_url(audio_track) if audio_track else None
            video_url = stream_url(video_track) if video_track else None
            # Legacy/non-DASH responses can contain a muxed stream.
            durl = data.get('durl') or []
            if durl:
                muxed = durl[0].get('url')
                audio_url = audio_url or muxed
                video_url = video_url or muxed
            return {'audio': audio_url, 'video': video_url}
        except Exception as e:
            logger.warning(f"获取视频媒体流地址失败 {bvid}: {e}")
            return {'audio': None, 'video': None}

    async def get_my_info(self) -> Optional[Dict[str, Any]]:
        """获取当前登录用户信息"""
        if not self.credential:
            return None

        try:
            my_info = await user.get_self_info(credential=self.credential)
            return {
                'mid': my_info.get('mid'),
                'name': my_info.get('name'),
                'face': my_info.get('face'),
                'level': my_info.get('level')
            }
        except Exception as e:
            logger.error(f"获取用户信息失败: {e}")
            return None


# 同步包装器（用于非异步环境）
class BilibiliAPISync:
    """B站API同步包装"""

    def __init__(self, credential_path: Path = None):
        self.api = BilibiliAPI(credential_path)
        self.loop = asyncio.new_event_loop()

    def __del__(self):
        try:
            self.loop.close()
        except Exception:  # noqa: BLE001 - 解释器退出阶段无法可靠处理
            pass

    def _run(self, coro):
        """运行协程"""
        return self.loop.run_until_complete(coro)

    def login_with_qr(self):
        return self._run(self.api.login_with_qr())

    def check_login(self):
        return self._run(self.api.check_login())

    def search_videos(self, keyword: str, page: int = 1):
        return self._run(self.api.search_videos(keyword, page))

    def get_subtitle(self, bvid: str):
        return self._run(self.api.get_subtitle(bvid))

    def get_comments(self, aid: int, count: int = 20):
        return self._run(self.api.get_comments(aid, count=count))

    def post_comment(self, aid: int, text: str):
        return self._run(self.api.post_comment(aid, text))

    def get_my_info(self):
        return self._run(self.api.get_my_info())
