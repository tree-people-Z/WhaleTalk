"""
数据库模块
使用SQLite存储历史记录（模型见 utils/db_models.py，迁移见 utils/db_migrations.py）
"""

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger
from sqlalchemy import create_engine, func
from sqlalchemy.orm import scoped_session, sessionmaker

from utils.db_migrations import apply_sqlite_pragmas, migrate_schema
from utils.db_models import (  # noqa: F401 - 向后兼容的重新导出
    AgentEvent,
    AgentSession,
    Base,
    CommentRecord,
    DailyQuota,
    GrowthItem,
    LikeRecord,
    MediaAsset,
    MemoryEvent,
    ObservedText,
    PrivateChatState,
    SearchKeywordRecord,
    ThreadState,
    VideoRecord,
)

class Database:
    """数据库管理器"""

    def __init__(self, db_path: str = "data/history.db"):
        """初始化数据库"""
        db_file = Path(db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)

        self.engine = create_engine(
            f'sqlite:///{db_path}',
            echo=False,
            connect_args={'timeout': 30},
            pool_pre_ping=True,
        )
        apply_sqlite_pragmas(self.engine)
        Base.metadata.create_all(self.engine)
        migrate_schema(self.engine)

        # 每个线程一个 Session：GUI 定时器与 Agent 工作线程不会共用连接。
        self._session_factory = scoped_session(
            sessionmaker(bind=self.engine, expire_on_commit=False)
        )

        logger.info(f"数据库已初始化: {db_path}")

    @property
    def session(self):
        """返回当前线程的 Session（scoped_session 保证线程隔离）。"""
        return self._session_factory()

    def close_session(self):
        """只释放当前线程的 Session，不关闭共享连接池。"""
        self._session_factory.remove()

    def dispose(self):
        """关闭所有连接（退出前调用）。"""
        self.close()

    def add_video_record(
        self,
        bvid: str,
        video_info: Dict[str, Any],
        analysis: Dict[str, Any]
    ) -> VideoRecord:
        """添加视频记录"""
        existing = self.session.query(VideoRecord).filter_by(bvid=bvid).first()
        if existing:
            # 更新
            existing.score = analysis.get('score', 0)
            existing.worthy = analysis.get('worthy', False)
            existing.reason = analysis.get('reason', '')
            existing.summary = analysis.get('summary', '')
            existing.analyzed_at = datetime.now()
            self.session.commit()
            return existing

        # 新增
        record = VideoRecord(
            bvid=bvid,
            aid=video_info.get('aid'),
            title=video_info.get('title'),
            author=video_info.get('author'),
            duration=video_info.get('duration'),
            pubdate=datetime.fromtimestamp(video_info.get('pubdate', 0)),
            analyzed_at=datetime.now(),
            score=analysis.get('score', 0),
            worthy=analysis.get('worthy', False),
            reason=analysis.get('reason', ''),
            summary=analysis.get('summary', '')
        )

        self.session.add(record)
        self.session.commit()
        logger.info(f"视频记录已添加: {bvid}")
        return record

    def mark_commented(self, bvid: str, comment_text: str, rpid: Optional[int] = None):
        """标记视频已评论"""
        record = self.session.query(VideoRecord).filter_by(bvid=bvid).first()
        if record:
            record.commented = True
            record.comment_text = comment_text
            record.commented_at = datetime.now()
            if rpid:
                sent_comment = self.session.query(CommentRecord).filter_by(
                    bvid=bvid, content=comment_text, comment_type='post', success=True
                ).order_by(CommentRecord.created_at.desc()).first()
                if sent_comment:
                    sent_comment.rpid = rpid
            self.session.commit()
            logger.info(f"已标记评论: {bvid}")

    def add_comment_record(
        self,
        bvid: str,
        aid: int,
        content: str,
        comment_type: str = "post",
        success: bool = True,
        error_message: str = "",
        rpid: Optional[int] = None,
        parent_rpid: Optional[int] = None,
        thread_root: Optional[int] = None,
        target_user: str = "",
        parent_content: str = ""
    ) -> CommentRecord:
        """添加评论记录"""
        record = CommentRecord(
            bvid=bvid,
            aid=aid,
            rpid=rpid,
            parent_rpid=parent_rpid,
            thread_root=thread_root,
            comment_type=comment_type,
            content=content,
            target_user=target_user,
            parent_content=parent_content,
            success=success,
            error_message=error_message
        )

        self.session.add(record)
        self.session.commit()
        return record

    def add_memory_event(
        self,
        event_type: str,
        *,
        user_name: str = "",
        user_mid: Optional[int] = None,
        aid: Optional[int] = None,
        bvid: str = "",
        video_title: str = "",
        content: str = "",
        my_content: str = "",
        outcome: str = "sent",
    ) -> MemoryEvent:
        event = MemoryEvent(
            event_type=event_type,
            user_name=user_name or "",
            user_mid=user_mid,
            aid=aid,
            bvid=bvid or "",
            video_title=video_title or "",
            content=content or "",
            my_content=my_content or "",
            outcome=outcome,
        )
        self.session.add(event)
        self.session.commit()
        return event

    def add_media_asset(
        self, path: str, source: str = '', source_url: str = '',
        description: str = '', tags: str = '',
    ) -> MediaAsset:
        asset = self.session.query(MediaAsset).filter_by(path=path).first()
        if asset is None:
            asset = MediaAsset(
                path=path, source=source, source_url=source_url,
                description=description, tags=tags,
            )
            self.session.add(asset)
        else:
            if description:
                asset.description = description
            if tags:
                asset.tags = tags
            asset.source = source or asset.source
        self.session.commit()
        return asset


    def get_dm_state(self, talker_id: int) -> int:
        state = self.session.query(PrivateChatState).filter_by(
            talker_id=int(talker_id)
        ).first()
        return int(state.last_replied_ts or 0) if state else 0

    def set_dm_state(self, talker_id: int, timestamp: int) -> None:
        state = self.session.query(PrivateChatState).filter_by(
            talker_id=int(talker_id)
        ).first()
        if state is None:
            state = PrivateChatState(talker_id=int(talker_id))
            self.session.add(state)
        state.last_replied_ts = int(timestamp or 0)
        state.updated_at = datetime.now()
        self.session.commit()

    def get_recent_memory_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        events = self.session.query(MemoryEvent)\
            .order_by(MemoryEvent.created_at.desc())\
            .limit(limit).all()
        return [{
            'event_type': event.event_type,
            'user_name': event.user_name,
            'user_mid': event.user_mid,
            'content': event.content,
            'my_content': event.my_content,
            'created_at': event.created_at,
        } for event in events]

    def add_like_record(
        self, bvid: str, aid: int, success: bool = True, error_message: str = ""
    ) -> LikeRecord:
        record = LikeRecord(
            bvid=bvid, aid=aid, success=success, error_message=error_message
        )
        self.session.add(record)
        self.session.commit()
        return record

    def get_today_like_count(self) -> int:
        start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        return self.session.query(LikeRecord).filter(
            LikeRecord.success == True,  # noqa: E712
            LikeRecord.created_at >= start,
        ).count()

    def has_liked_video(self, bvid: str) -> bool:
        return self.session.query(LikeRecord).filter(
            LikeRecord.bvid == bvid,
            LikeRecord.success == True,  # noqa: E712
        ).first() is not None

    def get_today_comment_count(self, include_replies: bool = False) -> int:
        """统计今天实际成功发出的顶层评论；可选包含回复。"""
        start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        query = self.session.query(CommentRecord).filter(
            CommentRecord.success == True,  # noqa: E712
            CommentRecord.created_at >= start,
        )
        if not include_replies:
            query = query.filter(CommentRecord.comment_type == 'post')
        return query.count()

    def get_today_quota(self) -> DailyQuota:
        """获取今日配额"""
        today = datetime.now().strftime('%Y-%m-%d')
        quota = self.session.query(DailyQuota).filter_by(date=today).first()

        if not quota:
            quota = DailyQuota(date=today)
            self.session.add(quota)
            self.session.commit()

        return quota

    def increment_comments(self):
        """增加今日评论计数"""
        quota = self.get_today_quota()
        quota.comments_sent += 1
        self.session.commit()

    def increment_videos(self):
        """增加今日分析视频计数"""
        quota = self.get_today_quota()
        quota.videos_analyzed += 1
        self.session.commit()

    def increment_runs(self):
        """增加今日运行次数"""
        quota = self.get_today_quota()
        quota.runs_completed += 1
        quota.last_run_at = datetime.now()
        self.session.commit()

    def has_commented_video(self, bvid: str) -> bool:
        """是否已经在某个视频下发过顶层评论。"""
        return self.session.query(CommentRecord).filter(
            CommentRecord.bvid == bvid,
            CommentRecord.comment_type == 'post',
            CommentRecord.success == True,  # noqa: E712
        ).first() is not None

    def check_video_commented_recently(self, bvid: str, days: int = 7) -> bool:
        """检查视频最近是否被评论过"""
        cutoff = datetime.now().timestamp() - (days * 86400)
        cutoff_dt = datetime.fromtimestamp(cutoff)

        record = self.session.query(VideoRecord).filter(
            VideoRecord.bvid == bvid,
            VideoRecord.commented == True,
            VideoRecord.commented_at >= cutoff_dt
        ).first()

        return record is not None

    def get_comments_missing_video(self, limit: int = 200) -> List[Dict[str, Any]]:
        """Return comments whose bvid or video title still needs backfilling."""
        from sqlalchemy import or_
        rows = self.session.query(
            CommentRecord.aid, CommentRecord.bvid
        ).outerjoin(
            VideoRecord, CommentRecord.bvid == VideoRecord.bvid
        ).filter(
            or_(
                CommentRecord.bvid == '',
                CommentRecord.bvid.is_(None),
                VideoRecord.id.is_(None),
                VideoRecord.title.is_(None),
                VideoRecord.title == '',
            )
        ).distinct().limit(limit).all()
        return [{'aid': row[0], 'bvid': row[1] or ''} for row in rows]

    def update_comment_bvid(self, aid: int, bvid: str) -> int:
        from sqlalchemy import or_
        count = self.session.query(CommentRecord).filter(
            CommentRecord.aid == int(aid),
            or_(CommentRecord.bvid == '', CommentRecord.bvid.is_(None)),
        ).update({CommentRecord.bvid: bvid}, synchronize_session=False)
        self.session.commit()
        return int(count or 0)

    def get_recent_comment_history(self, limit: int = 200) -> List[Dict[str, Any]]:
        """Sent comments/replies with video title and link for the history tab."""
        rows = self.session.query(CommentRecord, VideoRecord).outerjoin(
            VideoRecord, CommentRecord.bvid == VideoRecord.bvid
        ).filter(
            CommentRecord.success == True  # noqa: E712
        ).order_by(
            CommentRecord.created_at.desc()
        ).limit(limit).all()
        results = []
        for comment, video in rows:
            bvid = comment.bvid or ''
            url = (
                f'https://www.bilibili.com/video/{bvid}' if bvid
                else (f'https://www.bilibili.com/video/av{comment.aid}' if comment.aid else '')
            )
            results.append({
                'created_at': comment.created_at,
                'title': (video.title if video else '') or bvid or '',
                'content': comment.content or '',
                'bvid': bvid,
                'aid': comment.aid,
                'url': url,
            })
        return results


    def ensure_video_record(
        self, bvid: str, aid: int, title: str = '', author: str = ''
    ) -> VideoRecord:
        """Create a title-only video row for comments sent by the free agent."""
        bvid = (bvid or '').strip()
        if not bvid:
            raise ValueError('bvid 为空')
        record = self.session.query(VideoRecord).filter_by(bvid=bvid).first()
        if record is not None:
            if title and not record.title:
                record.title = title
                record.author = author or record.author
                self.session.commit()
            return record
        record = VideoRecord(
            bvid=bvid,
            aid=aid,
            title=title or '',
            author=author or '',
            analyzed_at=None,
        )
        self.session.add(record)
        self.session.commit()
        return record

    def add_agent_session(
        self, summary: str, actions: List[str], comments_sent: int = 0,
        videos: List[Dict[str, Any]] | None = None,
    ) -> None:
        self.session.add(AgentSession(
            summary=summary or '',
            actions_json=json.dumps(actions or [], ensure_ascii=False),
            videos_json=json.dumps(videos or [], ensure_ascii=False),
            comments_sent=int(comments_sent or 0),
        ))
        self.session.commit()

    def get_agent_event_states(self, keys: List[str]) -> Dict[str, Dict[str, Any]]:
        keys = [key for key in keys if key]
        if not keys:
            return {}
        rows = self.session.query(AgentEvent).filter(
            AgentEvent.event_key.in_(keys)
        ).all()
        return {
            row.event_key: {
                'status': row.status or 'delivered',
                'delivery_count': int(row.delivery_count or 0),
                'last_delivered_at': row.last_delivered_at,
            }
            for row in rows
        }

    def deliver_agent_events(self, events: List[Dict[str, Any]]) -> None:
        if not events:
            return
        keys = [str(item.get('key') or '') for item in events]
        rows = self.session.query(AgentEvent).filter(
            AgentEvent.event_key.in_(keys)
        ).all()
        existing = {row.event_key: row for row in rows}
        now = datetime.now()
        changed = False
        for item in events:
            key = str(item.get('key') or '')
            if not key:
                continue
            row = existing.get(key)
            if row is None:
                self.session.add(AgentEvent(
                    event_key=key,
                    event_type=str(item.get('type') or ''),
                    payload_json=json.dumps(
                        item.get('payload') or {}, ensure_ascii=False, default=str
                    ),
                    status='delivered',
                    delivery_count=1,
                    last_delivered_at=now,
                ))
                changed = True
                continue
            if (row.status or 'delivered') in ('handled', 'ignored'):
                continue
            row.delivery_count = int(row.delivery_count or 0) + 1
            row.last_delivered_at = now
            if row.delivery_count >= 3:
                row.status = 'ignored'
            changed = True
        if changed:
            self.session.commit()

    def mark_agent_events_handled(self, event_types: Optional[List[str]] = None) -> int:
        query = self.session.query(AgentEvent).filter(
            AgentEvent.status == 'delivered'
        )
        if event_types:
            query = query.filter(AgentEvent.event_type.in_(event_types))
        now = datetime.now()
        count = query.update(
            {AgentEvent.status: 'handled', AgentEvent.handled_at: now},
            synchronize_session=False,
        )
        self.session.commit()
        return int(count or 0)

    def record_search_keyword(self, keyword: str) -> None:
        keyword = str(keyword or '').strip()
        if not keyword:
            return
        self.session.add(SearchKeywordRecord(keyword=keyword))
        self.session.commit()

    def get_recent_search_keywords(self, limit: int = 8) -> List[str]:
        rows = self.session.query(SearchKeywordRecord)\
            .order_by(SearchKeywordRecord.created_at.desc())\
            .limit(max(1, int(limit))).all()
        return [row.keyword for row in rows]

    def get_recent_agent_sessions(self, limit: int = 100) -> List[Dict[str, Any]]:
        rows = self.session.query(AgentSession)\
            .order_by(AgentSession.created_at.desc())\
            .limit(limit)\
            .all()
        results = []
        for row in rows:
            try:
                actions = json.loads(row.actions_json or '[]')
            except (TypeError, ValueError):
                actions = []
            try:
                videos = json.loads(row.videos_json or '[]')
            except (TypeError, ValueError):
                videos = []
            results.append({
                'created_at': row.created_at,
                'summary': row.summary or '',
                'actions': actions if isinstance(actions, list) else [],
                'videos': videos if isinstance(videos, list) else [],
                'comments_sent': row.comments_sent or 0,
            })
        return results

    def is_video_analyzed_recently(self, bvid: str, hours: float = 2) -> bool:
        """检查视频是否在最近一段时间内分析过。"""
        cutoff = datetime.now() - timedelta(hours=hours)
        return self.session.query(VideoRecord).filter(
            VideoRecord.bvid == bvid,
            VideoRecord.analyzed_at.isnot(None),
            VideoRecord.analyzed_at >= cutoff,
        ).first() is not None

    def get_thread_state(self, thread_root: int) -> Dict[str, Any]:
        state = self.session.query(ThreadState).filter_by(
            thread_root=int(thread_root)
        ).first()
        if state is None:
            return {
                'bot_participated': False,
                'reply_count': 0,
                'last_reply_at': None,
            }
        return {
            'bot_participated': bool(state.bot_participated),
            'reply_count': int(state.reply_count or 0),
            'last_reply_at': state.last_reply_at,
        }

    def record_thread_reply(self, thread_root: int) -> None:
        state = self.session.query(ThreadState).filter_by(
            thread_root=int(thread_root)
        ).first()
        now = datetime.now()
        if state is None:
            state = ThreadState(thread_root=int(thread_root))
            self.session.add(state)
        elif state.last_reply_at and state.last_reply_at.date() != now.date():
            state.reply_count = 0
        state.bot_participated = True
        state.reply_count = int(state.reply_count or 0) + 1
        state.last_reply_at = now
        state.updated_at = now
        self.session.commit()


    def get_recent_comments(
        self, limit: int = 20, include_replies: bool = False
    ) -> List[Dict[str, Any]]:
        """获取最近发送的评论记录（可包含回复）"""
        query = self.session.query(CommentRecord)\
            .filter(CommentRecord.success == True)
        if not include_replies:
            query = query.filter(CommentRecord.comment_type == 'post')
        records = query.order_by(
            CommentRecord.created_at.desc(), CommentRecord.id.desc()
        ).limit(limit).all()

        results = []
        for record in records:
            video = self.session.query(VideoRecord).filter_by(bvid=record.bvid).first()
            stored_root = getattr(record, 'thread_root', None)
            thread_root = (
                stored_root
                or (
                    record.parent_rpid
                    if record.comment_type == 'reply' and record.parent_rpid
                    else record.rpid
                )
            )
            results.append({
                'aid': record.aid,
                'bvid': record.bvid,
                'rpid': record.rpid,
                'parent_rpid': record.parent_rpid,
                'thread_root': thread_root,
                'thread_root_known': bool(stored_root),
                'comment_type': record.comment_type,
                'target_user': record.target_user or '',
                'parent_content': record.parent_content or '',
                'content': record.content or '',
                'video_title': video.title if video else '',
                'commented_at': record.created_at,
            })

        return results

    def get_replied_comment_ids(self) -> set:
        """读取已回复过的原评论ID，避免重启后重复回复。"""
        return {
            row[0] for row in self.session.query(CommentRecord.parent_rpid)
            .filter(CommentRecord.comment_type == 'reply', CommentRecord.success == True,
                    CommentRecord.parent_rpid.isnot(None)).all()
        }

    def get_own_comment_rpids(self) -> set:
        """读取自己发出过的评论/回复 rpid，避免把自己当作回复对象。"""
        return {
            row[0] for row in self.session.query(CommentRecord.rpid)
            .filter(CommentRecord.rpid.isnot(None)).all()
        }

    # ------------------------------------------------------------ 在线学习
    def record_observed_texts(
        self, texts: List[str], source: str = 'comment'
    ) -> int:
        """记录 B 站公开文本，供后续提炼语言/梗/经验。"""
        added = 0
        now = datetime.now()
        for raw in texts or []:
            text = str(raw or '').strip()
            if not 6 <= len(text) <= 400:
                continue
            digest = hashlib.sha1(text.encode('utf-8')).hexdigest()
            row = self.session.query(ObservedText).filter_by(
                digest=digest
            ).first()
            if row:
                row.seen_count = int(row.seen_count or 0) + 1
                row.last_seen_at = now
                continue
            self.session.add(ObservedText(
                digest=digest,
                text=text,
                source=str(source or '')[:40],
                seen_count=1,
                created_at=now,
                last_seen_at=now,
            ))
            added += 1
        if added:
            self.session.commit()
        return added

    def get_observed_texts(
        self, since_days: int = 7, limit: int = 200
    ) -> List[Dict[str, Any]]:
        since = datetime.now() - timedelta(days=max(1, int(since_days)))
        rows = self.session.query(ObservedText).filter(
            ObservedText.last_seen_at >= since
        ).order_by(
            ObservedText.seen_count.desc(),
            ObservedText.last_seen_at.desc(),
        ).limit(max(1, int(limit))).all()
        return [
            {
                'text': row.text or '',
                'source': row.source or '',
                'seen_count': int(row.seen_count or 0),
            }
            for row in rows
        ]

    def prune_observed_texts(
        self, keep_days: int = 30, max_rows: int = 2000
    ) -> int:
        cutoff = datetime.now() - timedelta(days=max(1, int(keep_days)))
        removed = self.session.query(ObservedText).filter(
            ObservedText.last_seen_at < cutoff
        ).delete(synchronize_session=False)
        total = self.session.query(ObservedText).count()
        if total > max_rows:
            stale_ids = [
                row.id for row in self.session.query(ObservedText.id)
                .order_by(ObservedText.last_seen_at.asc())
                .limit(total - max_rows).all()
            ]
            if stale_ids:
                removed += self.session.query(ObservedText).filter(
                    ObservedText.id.in_(stale_ids)
                ).delete(synchronize_session=False)
        self.session.commit()
        return int(removed or 0)

    def upsert_growth_item(
        self,
        kind: str,
        title: str,
        content: str = '',
        example: str = '',
        source: str = '',
        weight: int = 100,
    ) -> Optional[int]:
        kind = str(kind or 'knowledge').strip()[:20]
        title = str(title or '').strip()[:80]
        if not kind or not title:
            return None
        key = f'{kind}:{title.casefold()}'
        row = self.session.query(GrowthItem).filter_by(key=key).first()
        now = datetime.now()
        if row:
            row.content = str(content or row.content or '')[:500]
            row.example = str(example or row.example or '')[:300]
            row.weight = min(200, int(row.weight or 0) + 10)
            row.enabled = True
            row.last_seen_at = now
        else:
            row = GrowthItem(
                key=key,
                kind=kind,
                title=title,
                content=str(content or '')[:500],
                example=str(example or '')[:300],
                source=str(source or '')[:60],
                weight=max(0, min(200, int(weight))),
                last_seen_at=now,
                created_at=now,
            )
            self.session.add(row)
        self.session.commit()
        return int(row.id)

    def get_growth_items(
        self, kinds: Optional[List[str]] = None, limit: int = 60,
        enabled_only: bool = True,
    ) -> List[Dict[str, Any]]:
        query = self.session.query(GrowthItem)
        if enabled_only:
            query = query.filter(GrowthItem.enabled == True)  # noqa: E712
        if kinds:
            query = query.filter(GrowthItem.kind.in_(kinds))
        rows = query.order_by(
            GrowthItem.weight.desc(),
            GrowthItem.use_count.desc(),
            GrowthItem.last_seen_at.desc(),
        ).limit(max(1, int(limit))).all()
        return [
            {
                'id': row.id,
                'kind': row.kind,
                'title': row.title,
                'content': row.content or '',
                'example': row.example or '',
                'weight': int(row.weight or 0),
                'use_count': int(row.use_count or 0),
                'last_used_at': row.last_used_at,
                'created_at': row.created_at,
            }
            for row in rows
        ]

    def mark_growth_used(self, item_ids: List[int]) -> int:
        ids = [int(item) for item in (item_ids or []) if item]
        if not ids:
            return 0
        now = datetime.now()
        updated = self.session.query(GrowthItem).filter(
            GrowthItem.id.in_(ids)
        ).update(
            {
                GrowthItem.use_count: GrowthItem.use_count + 1,
                GrowthItem.last_used_at: now,
            },
            synchronize_session=False,
        )
        self.session.commit()
        return int(updated or 0)

    def decay_growth_items(
        self, days: int = 14, amount: int = 12
    ) -> int:
        cutoff = datetime.now() - timedelta(days=max(1, int(days)))
        rows = self.session.query(GrowthItem).filter(
            GrowthItem.enabled == True,  # noqa: E712
            GrowthItem.created_at < cutoff,
            (GrowthItem.last_used_at.is_(None))
            | (GrowthItem.last_used_at < cutoff),
        ).all()
        changed = 0
        for row in rows:
            row.weight = max(0, int(row.weight or 0) - max(1, int(amount)))
            if row.weight <= 0:
                row.enabled = False
            changed += 1
        if changed:
            self.session.commit()
        return changed

    def prune_growth_items(self, max_items: int = 60) -> int:
        max_items = max(10, int(max_items))
        rows = self.session.query(GrowthItem).order_by(
            GrowthItem.enabled.desc(),
            GrowthItem.weight.desc(),
            GrowthItem.last_seen_at.desc(),
        ).all()
        removed = 0
        for index, row in enumerate(rows):
            if index < max_items:
                continue
            self.session.delete(row)
            removed += 1
        if removed:
            self.session.commit()
        return removed

    def get_recent_own_comments(self, limit: int = 20) -> List[str]:
        rows = self.session.query(CommentRecord.content).filter(
            CommentRecord.success == True,  # noqa: E712
        ).order_by(
            CommentRecord.created_at.desc(), CommentRecord.id.desc()
        ).limit(max(1, int(limit))).all()
        return [row[0] or '' for row in rows if (row[0] or '').strip()]

    def delete_growth_item(self, item_id: int) -> int:
        removed = self.session.query(GrowthItem).filter(
            GrowthItem.id == int(item_id)
        ).delete(synchronize_session=False)
        self.session.commit()
        return int(removed or 0)

    def clear_growth_items(self) -> int:
        removed = self.session.query(GrowthItem).delete(
            synchronize_session=False
        )
        self.session.commit()
        return int(removed or 0)

    def growth_counts(self) -> Dict[str, int]:
        rows = self.session.query(
            GrowthItem.kind, func.count(GrowthItem.id)
        ).filter(GrowthItem.enabled == True).group_by(  # noqa: E712
            GrowthItem.kind
        ).all()
        return {str(kind): int(count) for kind, count in rows}

    def get_activity_days(self, days: int = 7) -> Dict[str, Any]:
        """最近 N 天的发送/回复/Agent 轮次，用于仪表盘迷你趋势图。"""
        days = max(1, min(30, int(days or 7)))
        start = (datetime.now() - timedelta(days=days - 1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        dates = [
            (start + timedelta(days=offset)).date().isoformat()
            for offset in range(days)
        ]
        posts = {date: 0 for date in dates}
        replies = {date: 0 for date in dates}
        runs = {date: 0 for date in dates}

        rows = self.session.query(
            func.date(CommentRecord.created_at),
            CommentRecord.comment_type,
            func.count(CommentRecord.id),
        ).filter(
            CommentRecord.success == True,  # noqa: E712
            CommentRecord.created_at >= start,
        ).group_by(
            func.date(CommentRecord.created_at), CommentRecord.comment_type
        ).all()
        for day, comment_type, count in rows:
            key = str(day)[:10]
            if key not in posts:
                continue
            if comment_type == 'reply':
                replies[key] += int(count or 0)
            else:
                posts[key] += int(count or 0)

        run_rows = self.session.query(
            func.date(AgentSession.created_at), func.count(AgentSession.id)
        ).filter(AgentSession.created_at >= start).group_by(
            func.date(AgentSession.created_at)
        ).all()
        for day, count in run_rows:
            key = str(day)[:10]
            if key in runs:
                runs[key] = int(count or 0)

        return {
            'dates': dates,
            'posts': [posts[date] for date in dates],
            'replies': [replies[date] for date in dates],
            'sent': [posts[date] + replies[date] for date in dates],
            'runs': [runs[date] for date in dates],
        }

    def get_today_agent_runs(self) -> int:
        """今天完成的 Agent 轮次。"""
        start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        return int(
            self.session.query(AgentSession).filter(
                AgentSession.created_at >= start
            ).count()
        )

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        total_videos = self.session.query(VideoRecord).count()
        total_comments = self.session.query(CommentRecord)\
            .filter(CommentRecord.success == True).count()  # noqa: E712
        total_agent_runs = self.session.query(AgentSession).count()

        today_quota = self.get_today_quota()
        today_posts = self.get_today_comment_count()
        today_total = self.get_today_comment_count(include_replies=True)

        return {
            'total_videos_analyzed': total_videos,
            'total_comments_sent': total_comments,
            'total_agent_runs': total_agent_runs,
            'today_comments': today_total,
            'today_posts': today_posts,
            'today_replies': max(0, today_total - today_posts),
            'today_videos': today_quota.videos_analyzed,
            'today_runs': today_quota.runs_completed
        }

    def close(self):
        """关闭数据库连接（当前线程 Session + 连接池）。"""
        self._session_factory.remove()
        self.engine.dispose()
        logger.info("数据库连接已关闭")
