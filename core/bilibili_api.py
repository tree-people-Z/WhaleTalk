"""
B站API封装模块
提供登录、搜索、字幕、评论等核心功能
"""

import asyncio
import json
import re
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

from bilibili_api import login_v2, search, video, comment, user
from bilibili_api import Credential
from bilibili_api.search import SearchObjectType, OrderVideo
from bilibili_api.comment import OrderType
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

        # 风控状态
        self.blocked_until: Optional[datetime] = None

    def _load_credential(self):
        """从文件加载凭证"""
        if self.credential_path.exists():
            try:
                with open(self.credential_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.credential = Credential(
                        sessdata=data.get('SESSDATA'),
                        bili_jct=data.get('bili_jct'),
                        buvid3=data.get('buvid3')
                    )
                logger.info("已加载B站登录凭证")
            except Exception as e:
                logger.warning(f"加载凭证失败: {e}")
                self.credential = None

    def _save_credential(self, sessdata: str, bili_jct: str, buvid3: str):
        """保存凭证到文件"""
        self.credential_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            'SESSDATA': sessdata,
            'bili_jct': bili_jct,
            'buvid3': buvid3,
            'saved_at': datetime.now().isoformat()
        }
        with open(self.credential_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        self.credential = Credential(
            sessdata=sessdata,
            bili_jct=bili_jct,
            buvid3=buvid3
        )
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

                        for cookie in session.cookie_jar:
                            if cookie.key == 'SESSDATA' and not sessdata:
                                sessdata = cookie.value
                            elif cookie.key == 'bili_jct' and not bili_jct:
                                bili_jct = cookie.value
                            elif cookie.key == 'buvid3' and not buvid3:
                                buvid3 = cookie.value

                        if sessdata and bili_jct:
                            # URL解码
                            from urllib.parse import unquote
                            sessdata = unquote(sessdata)
                            bili_jct = unquote(bili_jct)
                            buvid3 = unquote(buvid3) if buvid3 else ""

                            logger.info(f"成功获取凭证")

                            # 保存凭证
                            self._save_credential(sessdata, bili_jct, buvid3)

                            # 创建Credential对象
                            self.credential = Credential(
                                sessdata=sessdata,
                                bili_jct=bili_jct,
                                buvid3=buvid3
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

    async def check_login(self) -> bool:
        """检查登录状态"""
        if not self.credential:
            return False

        try:
            u = user.User(self.credential.sessdata.split('=')[0], credential=self.credential)
            info = await u.get_user_info()
            logger.info(f"登录有效，用户: {info.get('name')}")
            return True
        except Exception as e:
            logger.warning(f"登录状态检查失败: {e}")
            return False

    def is_blocked(self) -> bool:
        """检查是否处于风控状态"""
        if self.blocked_until:
            if datetime.now() < self.blocked_until:
                return True
            else:
                self.blocked_until = None
        return False

    def set_blocked(self, duration_minutes: int = 30):
        """设置风控状态"""
        self.blocked_until = datetime.now() + timedelta(minutes=duration_minutes)
        logger.warning(f"触发风控，将暂停 {duration_minutes} 分钟")

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

            audio_url = stream_url(audio_tracks[0]) if audio_tracks else None
            video_url = stream_url(video_tracks[0]) if video_tracks else None
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

    async def get_comments(
        self,
        aid: int,
        sort: int = 2,  # 2=热门, 0=时间
        count: int = 20,
        include_replies: bool = False,
        root_rpids: Optional[set] = None
    ) -> List[Dict[str, Any]]:
        """获取视频评论"""
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
                        'content': entry.get('content', {}).get('message', ''),
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
                                'content': entry.get('content', {}).get('message', ''),
                                'like': entry.get('like', 0),
                                'ctime': entry.get('ctime', 0),
                                'root': entry.get('root') or root_rpid,
                                'parent': entry.get('parent', 0)
                            })
                            seen.add(entry.get('rpid'))
                    except Exception as exc:
                        logger.debug(f"按评论ID获取楼中楼失败 aid={aid}, root={root_rpid}: {exc}")

            logger.info(f"获取评论成功, aid={aid}, 数量: {len(comments)}")
            return comments

        except Exception as e:
            logger.error(f"获取评论失败 aid={aid}: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []
            return []

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
            logger.error(f"发送评论失败: {e}")

            # 检测风控
            if any(keyword in str(e) for keyword in ["412", "风控", "频繁", "验证码"]):
                self.set_blocked(30)

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
