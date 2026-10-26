"""
B站API封装模块
提供登录、搜索、字幕、评论等核心功能
"""

import asyncio
import json
import random
import re
import time
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

from bilibili_api import login_v2, search, video, comment, user
from bilibili_api import favorite_list, dynamic
from bilibili_api import session as bili_session
from bilibili_api import Credential
from bilibili_api.search import SearchObjectType, OrderVideo
from bilibili_api.comment import OrderType
from bilibili_api.user import RelationType
from loguru import logger
import qrcode
from io import BytesIO


class BilibiliAPI:
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
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"配置 B 站请求参数失败: {exc}")

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

    def _load_credential(self):
        """从文件加载凭证"""
        if self.credential_path.exists():
            try:
                with open(self.credential_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.credential = Credential(
                        sessdata=data.get('SESSDATA'),
                        bili_jct=data.get('bili_jct'),
                        buvid3=data.get('buvid3'),
                        buvid4=data.get('buvid4'),
                        dedeuserid=data.get('dedeuserid') or data.get('DedeUserID'),
                        ac_time_value=data.get('ac_time_value'),
                    )
                logger.info("已加载B站登录凭证")
            except Exception as e:
                logger.warning(f"加载凭证失败: {e}")
                self.credential = None

    def _save_credential(
        self,
        sessdata: str,
        bili_jct: str,
        buvid3: str,
        buvid4: str = '',
        dedeuserid: str = '',
        ac_time_value: str = '',
    ):
        """保存凭证到文件"""
        self.credential_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            'SESSDATA': sessdata,
            'bili_jct': bili_jct,
            'buvid3': buvid3,
            'buvid4': buvid4,
            'dedeuserid': dedeuserid,
            'ac_time_value': ac_time_value,
            'saved_at': datetime.now().isoformat()
        }
        with open(self.credential_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        self.credential = Credential(
            sessdata=sessdata,
            bili_jct=bili_jct,
            buvid3=buvid3,
            buvid4=buvid4 or None,
            dedeuserid=dedeuserid or None,
            ac_time_value=ac_time_value or None,
        )
        self._self_info = None
        logger.info("凭证已保存")

    async def login_with_qr(self) -> tuple[bool, Optional[bytes], Optional[any]]:
        """
        二维码登录

        Returns:
            (成功状态, 二维码图片字节, 登录对象)
        """
        try:
            # 使用新版API创建二维码登录对象
            qr_login = login_v2.QrCodeLogin()

            # 生成二维码（异步方法）
            await qr_login.generate_qrcode()

            # 获取二维码图片对象
            qr_picture = qr_login.get_qrcode_picture()

            if not qr_picture:
                logger.error("无法获取二维码图片")
                return False, None, None

            # 获取图片字节数据
            qr_image = qr_picture.content

            logger.info("二维码已生成，等待扫描...")

            return True, qr_image, qr_login

        except Exception as e:
            logger.error(f"生成二维码失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False, None, None

    async def check_qr_status(self, qr_login: any) -> Dict[str, Any]:
        """
        检查二维码扫描状态

        Args:
            qr_login: QrCodeLogin对象

        Returns:
            {'status': 'success/waiting/expired', 'credential': {...}}
        """
        try:
            from bilibili_api.login_v2 import API
            from bilibili_api import Api
            import aiohttp

            # 手动检查状态
            qr_key = qr_login._QrCodeLogin__qr_key
            api = API["qrcode"]["web"]["get_events"]
            params = {"qrcode_key": qr_key}
            events = await Api(credential=Credential(), **api).update_params(**params).result

            code = events.get("code")

            if code == 0:
                # 登录成功，获取crossDomain URL
                cross_domain_url = events.get("url")
                refresh_token = events.get("refresh_token")

                logger.info(f"登录成功，正在获取cookies...")

                # 访问crossDomain URL获取真正的cookies
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    'Referer': 'https://www.bilibili.com/',
                }

                connector = aiohttp.TCPConnector(ssl=False)
                async with aiohttp.ClientSession(connector=connector) as session:
                    async with session.get(cross_domain_url, headers=headers, allow_redirects=True) as resp:
                        # 从cookies中提取
                        sessdata = ""
                        bili_jct = ""
                        buvid3 = ""
                        buvid4 = ""
                        dedeuserid = ""
                        ac_time_value = ""

                        for cookie in session.cookie_jar:
                            if cookie.key == 'SESSDATA' and not sessdata:
                                sessdata = cookie.value
                            elif cookie.key == 'bili_jct' and not bili_jct:
                                bili_jct = cookie.value
                            elif cookie.key == 'buvid3' and not buvid3:
                                buvid3 = cookie.value
                            elif cookie.key == 'buvid4' and not buvid4:
                                buvid4 = cookie.value
                            elif cookie.key == 'DedeUserID' and not dedeuserid:
                                dedeuserid = cookie.value
                            elif cookie.key == 'ac_time_value' and not ac_time_value:
                                ac_time_value = cookie.value

                        if sessdata and bili_jct:
                            # URL解码
                            from urllib.parse import unquote
                            sessdata = unquote(sessdata)
                            bili_jct = unquote(bili_jct)
                            buvid3 = unquote(buvid3) if buvid3 else ""
                            buvid4 = unquote(buvid4) if buvid4 else ""
                            dedeuserid = unquote(dedeuserid) if dedeuserid else ""
                            ac_time_value = (
                                unquote(ac_time_value) if ac_time_value else ""
                            )

                            logger.info(f"成功获取凭证")

                            # 保存凭证
                            self._save_credential(
                                sessdata, bili_jct, buvid3,
                                buvid4, dedeuserid, ac_time_value,
                            )

                            # 创建Credential对象
                            self.credential = Credential(
                                sessdata=sessdata,
                                bili_jct=bili_jct,
                                buvid3=buvid3,
                                buvid4=buvid4 or None,
                                dedeuserid=dedeuserid or None,
                                ac_time_value=ac_time_value or None,
                            )

                            return {
                                'status': 'success',
                                'credential': self.credential
                            }
                        else:
                            logger.error("未能从crossDomain URL获取到cookies")
                            return {'status': 'error', 'message': '未能获取cookies'}

            elif code == 86101:
                return {'status': 'waiting'}
            elif code == 86090:
                return {'status': 'waiting'}
            elif code == 86038:
                return {'status': 'expired', 'message': '二维码已过期'}
            else:
                return {'status': 'waiting'}

        except Exception as e:
            logger.error(f"检查二维码状态失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {'status': 'error', 'message': str(e)}

    async def get_self_info(self) -> Dict[str, Any]:
        """获取当前登录账号的 uid 和昵称（缓存）。"""
        if self._self_info is not None:
            return self._self_info
        if not self.credential:
            return {}
        try:
            info = await user.get_self_info(self.credential)
            self._self_info = {
                'uid': info.get('mid'),
                'name': info.get('name') or '',
            }
        except Exception as exc:
            logger.debug(f"获取登录账号信息失败: {exc}")
            self._self_info = {}
        return self._self_info

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

    @staticmethod
    def _message_text(message: Dict[str, Any]) -> str:
        """Extract readable text from a private-message payload."""
        content = message.get('content')
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except (TypeError, ValueError):
                return content.strip()
        if isinstance(content, dict):
            for key in ('content', 'text', 'title'):
                value = content.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            return '[非文本消息]'
        return '' if content is None else str(content)

    async def get_private_sessions(self, session_type: int = 1) -> List[Dict[str, Any]]:
        """获取私信会话列表。session_type: 1 私信, 4 全部。"""
        if not self.credential:
            return []
        try:
            data = await bili_session.get_sessions(
                credential=self.credential, session_type=session_type
            )
        except Exception as exc:
            logger.warning(f"获取私信会话失败: {exc}")
            return []

        sessions = []
        for item in (data.get('session_list') or []):
            talker_id = item.get('talker_id')
            if not talker_id:
                continue
            last = item.get('last_msg') or {}
            account = item.get('account_info') or {}
            sessions.append({
                'talker_id': int(talker_id),
                'session_type': item.get('session_type') or session_type,
                'name': account.get('name') or item.get('name') or f'UID {talker_id}',
                'unread': int(item.get('unread_count') or 0),
                'last_message': self._message_text(last),
                'last_sender_uid': last.get('sender_uid'),
                'last_timestamp': int(last.get('timestamp') or item.get('top_ts') or 0),
            })
        sessions.sort(key=lambda row: row.get('last_timestamp') or 0, reverse=True)
        return sessions

    async def get_private_messages(
        self, talker_id: int, session_type: int = 1
    ) -> List[Dict[str, Any]]:
        """获取与某个用户的私信消息（按时间升序）。"""
        if not self.credential:
            return []
        try:
            data = await bili_session.fetch_session_msgs(
                talker_id=int(talker_id),
                credential=self.credential,
                session_type=session_type,
            )
        except Exception as exc:
            logger.warning(f"获取私信消息失败 talker={talker_id}: {exc}")
            return []

        messages = []
        for item in (data.get('messages') or []):
            if item.get('msg_type') == 5:  # 撤回的消息
                content = '[消息已撤回]'
            else:
                content = self._message_text(item)
            messages.append({
                'sender_uid': item.get('sender_uid'),
                'timestamp': int(item.get('timestamp') or 0),
                'content': content,
                'msg_type': item.get('msg_type'),
            })
        messages.sort(key=lambda row: row.get('timestamp') or 0)
        return messages

    async def check_login(self) -> bool:
        """检查登录状态"""
        if not self.credential:
            return False

        try:
            # 老版本 cookies 可能没有 buvid4，补一个可降低 412 概率。
            if self.credential and not getattr(self.credential, 'buvid4', None):
                try:
                    from bilibili_api.utils.network import get_buvid
                    _, buvid4 = await get_buvid()
                    if buvid4:
                        self.credential.buvid4 = buvid4
                        self._save_credential(
                            self.credential.sessdata or '',
                            self.credential.bili_jct or '',
                            self.credential.buvid3 or '',
                            buvid4,
                            self.credential.dedeuserid or '',
                            self.credential.ac_time_value or '',
                        )
                        logger.info("已补充 buvid4 风控参数")
                except Exception as exc:  # noqa: BLE001
                    logger.debug(f"补充 buvid4 失败: {exc}")
            info = await user.get_self_info(credential=self.credential)
            if not isinstance(info, dict) or not info.get('name'):
                logger.warning("登录状态检查失败: 未获取到用户信息")
                return False
            logger.info(f"登录有效，用户: {info.get('name')}")
            return True
        except Exception as e:
            logger.warning(f"登录状态检查失败: {e}")
            return False

    def is_blocked(self) -> bool:
        """检查是否处于风控状态"""
        blocked_until = getattr(self, 'blocked_until', None)
        if blocked_until:
            if datetime.now() < blocked_until:
                return True
            else:
                self.blocked_until = None
        return False

    def set_blocked(self, duration_minutes: int = 30):
        """设置风控状态"""
        self.blocked_until = datetime.now() + timedelta(minutes=duration_minutes)
        logger.warning(f"触发风控，将暂停 {duration_minutes} 分钟")

    def _load_posting_state(self):
        path = getattr(self, '_posting_state_path', None)
        if not path or not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            until = datetime.fromisoformat(data.get('until', ''))
        except Exception:  # noqa: BLE001
            return
        if until and datetime.now() < until:
            self.posting_blocked_until = until
            self.posting_block_reason = data.get('reason', '')
            logger.info(f"恢复评论发送冷却至 {until:%Y-%m-%d %H:%M}")
        else:
            try:
                path.unlink()
            except OSError:
                pass

    def _save_posting_state(self):
        path = getattr(self, '_posting_state_path', None)
        if not path:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({
                'until': self.posting_blocked_until.isoformat()
                if self.posting_blocked_until else '',
                'reason': self.posting_block_reason,
            }, ensure_ascii=False), encoding='utf-8')
        except OSError:
            pass

    def _clear_posting_state(self):
        path = getattr(self, '_posting_state_path', None)
        if path:
            try:
                path.unlink()
            except OSError:
                pass

    def is_posting_blocked(self) -> bool:
        """B站评论发送额度是否已用完（错误码 12014）。"""
        until = getattr(self, 'posting_blocked_until', None)
        if until:
            if datetime.now() < until:
                return True
            self.posting_blocked_until = None
            self._clear_posting_state()
        return False

    def set_posting_blocked(self, reason: str = ''):
        """暂停发评论到次日凌晨，避免反复触发 12014。"""
        reset = (datetime.now() + timedelta(days=1)).replace(
            hour=0, minute=5, second=0, microsecond=0
        )
        self.posting_blocked_until = reset
        self.posting_block_reason = reason
        self._save_posting_state()
        logger.warning(
            f"B站评论发送已达上限（12014），暂停发评论至 "
            f"{reset:%Y-%m-%d %H:%M}"
        )

    @staticmethod
    def _short_error(message: str, limit: int = 160) -> str:
        """Collapse B站 HTML error bodies so logs stay readable."""
        text = re.sub(r'<[^>]+>', ' ', message or '')
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:limit] + ('…' if len(text) > limit else '')

    async def _pace_comment_request(self) -> None:
        """Serialize comment requests with a minimum interval.

        The API object is shared by several workers, each of which runs its own
        event loop. asyncio.Lock is bound to the loop that first uses it, so the
        lock must be recreated when the running loop changes.
        """
        loop = asyncio.get_running_loop()
        lock = getattr(self, '_comment_request_lock', None)
        if lock is None or getattr(self, '_comment_request_lock_loop', None) is not loop:
            lock = asyncio.Lock()
            self._comment_request_lock = lock
            self._comment_request_lock_loop = loop
        async with lock:
            # 固定间隔之外再加随机抖动，避免形成规律的机器请求节奏。
            target = (
                getattr(self, '_last_comment_request_at', 0.0)
                + getattr(self, '_comment_min_interval', 2.0)
                + random.uniform(0, 1.5)
            )
            wait = target - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_comment_request_at = time.monotonic()

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

    async def get_video_info(self, bvid: str) -> Optional[Dict[str, Any]]:
        """获取视频详细信息"""
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
        except Exception as e:
            logger.error(f"获取视频信息失败 {bvid}: {e}")
            return None

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

    @staticmethod
    def _extract_comment_images(content: Dict[str, Any]) -> List[str]:
        """提取评论里的图片地址（B站单图/多图字段都兼容）。"""
        urls: List[str] = []

        def add(value):
            if isinstance(value, str):
                url = value.strip()
            elif isinstance(value, dict):
                url = value.get('img_src') or value.get('url') or value.get('src') or ''
            else:
                return
            if url.startswith('//'):
                url = 'https:' + url
            if url.startswith('http') and url not in urls:
                urls.append(url)

        pictures = content.get('pictures')
        if isinstance(pictures, list):
            for picture in pictures:
                add(picture)
        add(content.get('picture'))
        add(content.get('pic'))
        return urls[:6]

    async def get_comments(
        self,
        aid: int,
        sort: int = 2,  # 2=热门, 0=时间
        count: int = 20,
        include_replies: bool = False,
        root_rpids: Optional[set] = None
    ) -> List[Dict[str, Any]]:
        """获取视频评论"""
        if self.is_blocked():
            logger.debug(f"风控冷却中，跳过获取评论 aid={aid}")
            return []
        closed_cache = getattr(self, '_closed_comment_aids', None)
        if closed_cache is None:
            closed_cache = {}
            self._closed_comment_aids = closed_cache
        closed_at = closed_cache.get(aid)
        if closed_at and (datetime.now() - closed_at).total_seconds() < 600:
            logger.debug(f"评论区已关闭（缓存），跳过 aid={aid}")
            return []
        cache_key = None
        comments_cache = getattr(self, '_comments_cache', None)
        if comments_cache is None:
            comments_cache = {}
            self._comments_cache = comments_cache
        if not include_replies:
            cache_key = (aid, sort, count)
            cached = comments_cache.get(cache_key)
            if cached and (datetime.now() - cached[0]).total_seconds() < 120:
                return list(cached[1])
        await self._pace_comment_request()
        try:
            # 转换排序参数为枚举
            order_type = OrderType.LIKE if sort == 2 else OrderType.TIME

            comments_data = await comment.get_comments(
                oid=aid,
                type_=comment.CommentResourceType.VIDEO,
                page_index=1,
                order=order_type,
                credential=self.credential
            )

            # 检查返回数据
            if not comments_data or 'replies' not in comments_data:
                logger.warning(f"视频 aid={aid} 没有评论或评论区已关闭")
                return []

            replies = comments_data.get('replies', [])
            if not replies:
                logger.info(f"视频 aid={aid} 暂无评论")
                return []

            comments = []
            fetched_roots = set()
            for c in replies[:count]:
                if not c:
                    continue
                entries = [c]
                # Top-level replies usually omit nested replies; fetch the
                # official sub-reply endpoint so replies to our comments are visible.
                root_rpid = c.get('rpid')
                if root_rpid and include_replies and (root_rpids is None or root_rpid in root_rpids):
                    try:
                        sub_data = await comment.Comment(
                            oid=aid,
                            type_=comment.CommentResourceType.VIDEO,
                            rpid=root_rpid,
                            credential=self.credential
                        ).get_sub_comments(page_index=1, page_size=20)
                        sub_replies = (sub_data.get('replies') or []) if isinstance(sub_data, dict) else []
                        entries.extend(sub_replies)
                        fetched_roots.add(root_rpid)
                    except Exception as exc:
                        logger.debug(f"获取楼中楼失败 aid={aid}, root={root_rpid}: {exc}")
                for entry in entries:
                    comments.append({
                        'rpid': entry.get('rpid'),
                        'user': entry.get('member', {}).get('uname', '未知用户'),
                        'mid': entry.get('member', {}).get('mid'),
                        'content': entry.get('content', {}).get('message', ''),
                        'images': self._extract_comment_images(entry.get('content') or {}),
                        'like': entry.get('like', 0),
                        'ctime': entry.get('ctime', 0),
                        'root': entry.get('root') or (root_rpid if entry is not c else 0),
                        'parent': entry.get('parent', 0)
                    })

            # A user's own top-level comment may not be present on the first
            # page (especially when sorted by likes), so fetch known roots by ID.
            if include_replies and root_rpids:
                seen = {item['rpid'] for item in comments if item.get('rpid')}
                for root_rpid in root_rpids - fetched_roots:
                    try:
                        sub_data = await comment.Comment(
                            oid=aid,
                            type_=comment.CommentResourceType.VIDEO,
                            rpid=root_rpid,
                            credential=self.credential
                        ).get_sub_comments(page_index=1, page_size=20)
                        for entry in (sub_data.get('replies') or []) if isinstance(sub_data, dict) else []:
                            if not entry or entry.get('rpid') in seen:
                                continue
                            comments.append({
                                'rpid': entry.get('rpid'),
                                'user': entry.get('member', {}).get('uname', '未知用户'),
                                'mid': entry.get('member', {}).get('mid'),
                                'content': entry.get('content', {}).get('message', ''),
                                'images': self._extract_comment_images(entry.get('content') or {}),
                                'like': entry.get('like', 0),
                                'ctime': entry.get('ctime', 0),
                                'root': entry.get('root') or root_rpid,
                                'parent': entry.get('parent', 0)
                            })
                            seen.add(entry.get('rpid'))
                    except Exception as exc:
                        logger.debug(f"按评论ID获取楼中楼失败 aid={aid}, root={root_rpid}: {exc}")

            if cache_key is not None:
                comments_cache[cache_key] = (datetime.now(), list(comments))
            logger.info(f"获取评论成功, aid={aid}, 数量: {len(comments)}")
            return comments

        except Exception as e:
            message = str(e)

            if '12002' in message or '评论功能已关闭' in message:
                closed_cache[aid] = datetime.now()
                logger.info(f"视频 aid={aid} 评论区已关闭，跳过")
                return []

            if "412" in message or any(
                keyword in message for keyword in ("风控", "频繁", "验证码")
            ):
                self.set_blocked(30)
                logger.warning(
                    f"获取评论触发 B 站 412 风控，暂停评论请求 30 分钟: aid={aid}"
                )
            else:
                logger.error(
                    f"获取评论失败 aid={aid}: {self._short_error(message)}"
                )
            return []

    async def _load_all_subcomments(
        self, aid: int, root_rpid: int, page_size: int = 20, max_pages: int = 20
    ) -> List[Dict[str, Any]]:
        """Load every page of a comment thread, not just the first page."""
        entries: List[Dict[str, Any]] = []
        seen = set()
        page_index = 1
        while page_index <= max_pages:
            try:
                sub_data = await comment.Comment(
                    oid=aid,
                    type_=comment.CommentResourceType.VIDEO,
                    rpid=root_rpid,
                    credential=self.credential,
                ).get_sub_comments(page_index=page_index, page_size=page_size)
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"获取楼中楼第 {page_index} 页失败 aid={aid}, root={root_rpid}: {exc}")
                break
            replies = (sub_data.get('replies') or []) if isinstance(sub_data, dict) else []
            new_entries = [
                entry for entry in replies
                if entry and entry.get('rpid') not in seen
            ]
            if not new_entries:
                break
            for entry in new_entries:
                seen.add(entry.get('rpid'))
                entries.append(entry)

            page_info = sub_data.get('page') or {}
            try:
                total = int(page_info.get('count') or page_info.get('acount') or 0)
            except (TypeError, ValueError):
                total = 0
            if total and len(entries) >= total:
                break
            if not total and len(replies) < page_size:
                break
            page_index += 1
            await asyncio.sleep(0.4)
        return entries

    async def get_comment_thread(
        self, aid: int, root_rpid: int, count: int = 50
    ) -> List[Dict[str, Any]]:
        """获取某条评论下的完整对话（我方楼层 + 网友回复），按时间排序。"""
        try:
            root_rpid = int(root_rpid)
        except (TypeError, ValueError):
            return []
        comments = await self.get_comments(
            aid, count=count, include_replies=True, root_rpids={root_rpid}
        )
        by_rpid = {}
        for item in comments:
            rpid = item.get('rpid')
            if rpid and rpid not in by_rpid:
                by_rpid[rpid] = item
        # get_comments only returns the first sub-comment page; fetch all pages
        # so the whole thread is visible.
        for entry in await self._load_all_subcomments(aid, root_rpid):
            rpid = entry.get('rpid')
            if rpid and rpid not in by_rpid:
                by_rpid[rpid] = {
                    'rpid': rpid,
                    'user': entry.get('member', {}).get('uname', '未知用户'),
                    'mid': entry.get('member', {}).get('mid'),
                    'content': entry.get('content', {}).get('message', ''),
                    'images': self._extract_comment_images(entry.get('content') or {}),
                    'like': entry.get('like', 0),
                    'ctime': entry.get('ctime', 0),
                    'root': entry.get('root') or root_rpid,
                    'parent': entry.get('parent', 0),
                }
        thread = [
            item for item in by_rpid.values()
            if item.get('root') == root_rpid or item.get('rpid') == root_rpid
        ]
        thread.sort(key=lambda item: item.get('ctime') or 0)
        seen = set()
        result = []
        for item in thread:
            rpid = item.get('rpid')
            if rpid in seen:
                continue
            seen.add(rpid)
            result.append(item)
        return result

    async def post_comment(
        self,
        aid: int,
        text: str,
        root_rpid: Optional[int] = None,
        parent_rpid: Optional[int] = None
    ) -> bool:
        """
        发送评论

        Args:
            aid: 视频aid
            text: 评论内容
            root_rpid: 回复的评论ID（楼中楼回复）

        Returns:
            是否成功
        """
        if self.is_blocked():
            logger.warning("当前处于风控状态，跳过评论")
            return False

        if self.is_posting_blocked():
            logger.info("评论发送限额冷却中，跳过本次发送")
            return False

        if not self.credential:
            logger.error("未登录，无法发送评论")
            return False

        try:
            self.last_comment_rpid = None
            response = await comment.send_comment(
                text=text,
                oid=aid,
                type_=comment.CommentResourceType.VIDEO,
                root=root_rpid,
                parent=parent_rpid,
                credential=self.credential
            )
            payload = response.get('data', response) if isinstance(response, dict) else {}
            self.last_comment_rpid = (
                payload.get('rpid') or payload.get('reply', {}).get('rpid')
                if isinstance(payload, dict) else None
            )

            logger.info(f"评论发送成功: {text[:30]}...")
            return True

        except Exception as e:
            message = str(e)

            if any(keyword in message for keyword in ('12014', '已达到当前评论发送上限')):
                self.set_posting_blocked(message[:120])
                return False

            logger.error(f"发送评论失败: {self._short_error(message)}")

            # 检测风控
            if any(keyword in message for keyword in ["412", "风控", "频繁", "验证码"]):
                self.set_blocked(30)

            return False

    async def like_video(self, aid: int) -> bool:
        """给视频点赞；已经赞过按成功处理。"""
        if not self.credential:
            logger.error("未登录，无法点赞")
            return False
        if self.is_blocked():
            logger.warning("当前处于风控状态，跳过点赞")
            return False
        try:
            await video.Video(aid=aid, credential=self.credential).like(True)
            logger.info(f"点赞视频成功: aid={aid}")
            return True
        except Exception as e:  # noqa: BLE001
            message = str(e)
            if any(keyword in message for keyword in ('65006', '已经赞', '已点赞')):
                logger.debug(f"视频已经点过赞: aid={aid}")
                return True
            logger.warning(f"点赞视频失败 aid={aid}: {self._short_error(message)}")
            return False

    async def like_comment(self, aid: int, rpid: int) -> bool:
        """给网友评论点赞；已经赞过按成功处理。"""
        if not self.credential or not rpid:
            return False
        try:
            await comment.Comment(
                oid=aid,
                type_=comment.CommentResourceType.VIDEO,
                rpid=rpid,
                credential=self.credential,
            ).like(True)
            logger.info(f"点赞评论成功: rpid={rpid}")
            return True
        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            if any(keyword in message for keyword in ('65006', '已经赞', '已点赞')):
                return True
            logger.debug(f"点赞评论失败 rpid={rpid}: {self._short_error(message)}")
            return False

    async def report_watch(self, bvid: str) -> bool:
        """上报一次观看进度，让账号更像真实观众（低频使用）。"""
        if not self.credential or self.is_blocked():
            return False
        try:
            viewer = video.Video(bvid=bvid, credential=self.credential)
            info = await viewer.get_info()
            duration = int(info.get('duration') or 0)
            cid = info.get('cid')
            await viewer.report_start_watching(page_index=0)
            if duration and cid:
                progress = max(1, int(duration * random.uniform(0.2, 0.7)))
                await viewer.report_watch_history(progress=progress, cid=cid)
            logger.info(f"已上报观看进度: {bvid}")
            return True
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"上报观看进度失败 {bvid}: {self._short_error(str(exc))}")
            return False

    async def favorite_video(self, aid: int) -> bool:
        """把视频收藏到默认收藏夹（已收藏则跳过）。"""
        if not self.credential or self.is_blocked():
            return False
        try:
            viewer = video.Video(aid=aid, credential=self.credential)
            if await viewer.has_favoured():
                return True
            info = await self.get_self_info()
            uid = info.get('uid')
            if not uid:
                return False
            data = await favorite_list.get_video_favorite_list(
                uid, credential=self.credential
            )
            folders = (data or {}).get('list') or []
            if not folders:
                return False
            folder_id = int(folders[0].get('id'))
            await viewer.set_favorite([folder_id])
            logger.info(f"收藏视频成功: aid={aid} folder={folder_id}")
            return True
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"收藏视频失败 aid={aid}: {self._short_error(str(exc))}")
            return False

    async def follow_user(self, uid: int) -> bool:
        """关注用户；已关注按成功处理。"""
        if not self.credential or not uid or self.is_blocked():
            return False
        try:
            info = await self.get_self_info()
            if info.get('uid') == uid:
                return False
            await user.User(uid, credential=self.credential).modify_relation(
                RelationType.SUBSCRIBE
            )
            logger.info(f"关注用户成功: {uid}")
            return True
        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            if any(keyword in message for keyword in ('已经关注', '已关注', '22001')):
                return True
            logger.debug(f"关注用户失败 {uid}: {self._short_error(message)}")
            return False

    async def follow_video_author(self, bvid: str) -> bool:
        info = await self.get_video_info(bvid)
        if not info:
            return False
        return await self.follow_user(info.get('owner_mid') or 0)

    async def like_latest_user_dynamic(self, uid: int) -> bool:
        """给某个 UP 最近一条动态点赞（低频行为）。"""
        if not self.credential or not uid or self.is_blocked():
            return False
        try:
            data = await user.User(uid, credential=self.credential).get_dynamics_new()
            for item in (data or {}).get('items') or []:
                dynamic_id = item.get('id_str') or item.get('id')
                if not dynamic_id:
                    continue
                await dynamic.Dynamic(
                    int(dynamic_id), credential=self.credential
                ).set_like(True)
                logger.info(f"点赞动态成功: uid={uid} dynamic={dynamic_id}")
                return True
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"点赞动态失败 uid={uid}: {self._short_error(str(exc))}")
        return False

    async def like_video_author_dynamic(self, bvid: str) -> bool:
        info = await self.get_video_info(bvid)
        if not info:
            return False
        return await self.like_latest_user_dynamic(info.get('owner_mid') or 0)

    async def post_video_dynamic(self, bvid: str, title: str) -> bool:
        """把视频分享成一条纯文本动态（低频、需显式开启）。"""
        if not self.credential or self.is_blocked():
            return False
        try:
            text = (
                f"看到这个视频：{title}\n"
                f"https://www.bilibili.com/video/{bvid}"
            )
            payload = dynamic.BuildDynamic.create_by_args(text=text)
            await dynamic.send_dynamic(payload, self.credential)
            logger.info(f"发布视频动态成功: {bvid}")
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"发布动态失败 {bvid}: {self._short_error(str(exc))}")
            return False

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
        except:
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
