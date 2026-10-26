"""B站视频互动、动态与弹幕。"""

from bilibili_api import dynamic, favorite_list, user, video
from bilibili_api.user import RelationType
from bilibili_api.utils.danmaku import Danmaku
from loguru import logger


class BiliInteractMixin:
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

    async def send_danmaku(self, bvid: str, text: str, dm_time: float = 1.0) -> bool:
        if not self.credential or self.is_blocked():
            return False
        try:
            await video.Video(bvid=bvid, credential=self.credential).send_danmaku(
                danmaku=Danmaku(text=text[:100], dm_time=max(0.0, dm_time))
            )
            logger.info(f"弹幕发送成功: {bvid}")
            return True
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"弹幕发送失败 {bvid}: {self._short_error(str(exc))}")
            return False

    async def like_video_danmaku(self, bvid: str) -> bool:
        if not self.credential or self.is_blocked():
            return False
        try:
            viewer = video.Video(bvid=bvid, credential=self.credential)
            danmakus = await viewer.get_danmakus(page_index=0)
            for danmaku in danmakus or []:
                dmid = getattr(danmaku, 'id_str', None) or getattr(danmaku, 'id', None)
                if dmid:
                    await viewer.like_danmaku(dmid=int(dmid), page_index=0)
                    logger.info(f"弹幕点赞成功: {bvid}")
                    return True
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"弹幕点赞失败 {bvid}: {self._short_error(str(exc))}")
        return False

    async def coin_video(self, aid: int, num: int = 1) -> bool:
        if not self.credential or self.is_blocked():
            return False
        try:
            viewer = video.Video(aid=aid, credential=self.credential)
            if await viewer.get_pay_coins() >= 2:
                return True
            await viewer.pay_coin(num=max(1, min(int(num), 2)), like=False)
            logger.info(f"投币成功: aid={aid}")
            return True
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"投币失败 aid={aid}: {self._short_error(str(exc))}")
            return False

    async def share_video(self, aid: int) -> bool:
        if not self.credential or self.is_blocked():
            return False
        try:
            await video.Video(aid=aid, credential=self.credential).share()
            logger.info(f"分享视频成功: aid={aid}")
            return True
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"分享视频失败 aid={aid}: {self._short_error(str(exc))}")
            return False

    async def add_to_watch_later(self, aid: int) -> bool:
        if not self.credential or self.is_blocked():
            return False
        try:
            await video.Video(aid=aid, credential=self.credential).add_to_toview()
            logger.info(f"稍后再看成功: aid={aid}")
            return True
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"稍后再看失败 aid={aid}: {self._short_error(str(exc))}")
            return False

    async def repost_latest_user_dynamic(self, uid: int, text: str = "转发动态") -> bool:
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
                ).repost(text)
                logger.info(f"转发动态成功: uid={uid} dynamic={dynamic_id}")
                return True
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"转发动态失败 uid={uid}: {self._short_error(str(exc))}")
        return False

    async def repost_video_author_dynamic(self, bvid: str) -> bool:
        info = await self.get_video_info(bvid)
        if not info:
            return False
        return await self.repost_latest_user_dynamic(info.get('owner_mid') or 0)
