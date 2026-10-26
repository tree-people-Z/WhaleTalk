"""B站评论读取、发送与点赞。"""

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

from bilibili_api import comment
from bilibili_api.comment import OrderType
from loguru import logger


class BiliCommentMixin:
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
