"""
数据库模块
使用SQLite存储历史记录
"""

from pathlib import Path
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Boolean, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker
from loguru import logger

Base = declarative_base()


class VideoRecord(Base):
    """视频记录表"""
    __tablename__ = 'videos'

    id = Column(Integer, primary_key=True)
    bvid = Column(String(20), unique=True, nullable=False, index=True)
    aid = Column(Integer)
    title = Column(String(200))
    author = Column(String(100))
    duration = Column(Integer)
    pubdate = Column(DateTime)

    # 分析结果
    analyzed_at = Column(DateTime)
    score = Column(Integer)  # 0-20分
    worthy = Column(Boolean)
    reason = Column(Text)
    summary = Column(Text)

    # 操作记录
    commented = Column(Boolean, default=False)
    comment_text = Column(Text)
    commented_at = Column(DateTime)

    # 元数据
    created_at = Column(DateTime, default=datetime.now)


class CommentRecord(Base):
    """评论记录表"""
    __tablename__ = 'comments'

    id = Column(Integer, primary_key=True)
    bvid = Column(String(20), nullable=False, index=True)
    aid = Column(Integer)
    rpid = Column(Integer)  # 评论ID
    parent_rpid = Column(Integer)  # 被回复的评论ID
    thread_root = Column(Integer)  # 楼层根评论ID（用于合并同一栋楼）

    comment_type = Column(String(20))  # 'post'=发出, 'reply'=回复
    content = Column(Text)
    target_user = Column(String(100))  # 回复的用户
    parent_content = Column(Text)  # 被回复评论的原文，用于按楼展示

    success = Column(Boolean)
    error_message = Column(Text)

    created_at = Column(DateTime, default=datetime.now)


class LikeRecord(Base):
    """视频点赞记录"""
    __tablename__ = 'likes'

    id = Column(Integer, primary_key=True)
    bvid = Column(String(20), nullable=False, index=True)
    aid = Column(Integer)
    success = Column(Boolean)
    error_message = Column(Text)
    created_at = Column(DateTime, default=datetime.now)


class MemoryEvent(Base):
    """长期记忆：一次与网友的互动。"""
    __tablename__ = 'memory_events'

    id = Column(Integer, primary_key=True)
    event_type = Column(String(30), index=True)  # reply/comment/greeting/requested_video
    user_name = Column(String(100))
    user_mid = Column(Integer, index=True)
    aid = Column(Integer)
    bvid = Column(String(20))
    video_title = Column(Text)
    content = Column(Text)       # 对方说的话
    my_content = Column(Text)    # 我说的话
    outcome = Column(String(30), default='sent')
    created_at = Column(DateTime, default=datetime.now, index=True)


class ThreadState(Base):
    """Per-thread conversation state for model-driven replies."""
    __tablename__ = 'thread_states'

    id = Column(Integer, primary_key=True)
    thread_root = Column(Integer, unique=True, index=True)
    bot_participated = Column(Boolean, default=False)
    reply_count = Column(Integer, default=0)
    last_reply_at = Column(DateTime)
    updated_at = Column(DateTime, default=datetime.now)


class MediaAsset(Base):
    """Collected images for later reuse (DM images, dynamic images, etc.)."""
    __tablename__ = 'media_assets'

    id = Column(Integer, primary_key=True)
    path = Column(Text, unique=True)
    source = Column(String(30))
    source_url = Column(Text)
    description = Column(Text)
    tags = Column(Text)
    created_at = Column(DateTime, default=datetime.now)
    used_count = Column(Integer, default=0)


class PrivateChatState(Base):
    """Last replied private-message timestamp per conversation."""
    __tablename__ = 'private_chat_state'

    id = Column(Integer, primary_key=True)
    talker_id = Column(Integer, unique=True, index=True)
    last_replied_ts = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.now)


class AgentSession(Base):
    """One free-agent run and the actions it actually performed."""
    __tablename__ = 'agent_sessions'

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=datetime.now, index=True)
    summary = Column(Text, default='')
    actions_json = Column(Text, default='[]')
    videos_json = Column(Text, default='[]')
    comments_sent = Column(Integer, default=0)


class SearchKeywordRecord(Base):
    """Search terms actually used, for keyword rotation."""
    __tablename__ = 'search_keywords'

    id = Column(Integer, primary_key=True)
    keyword = Column(String(100), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.now, index=True)


class AgentEvent(Base):
    """Persistent inbox state so the same @/comment/DM is handled once."""
    __tablename__ = 'agent_events'

    id = Column(Integer, primary_key=True)
    event_key = Column(String(160), unique=True, nullable=False, index=True)
    event_type = Column(String(30), index=True)
    payload_json = Column(Text, default='{}')
    status = Column(String(20), default='delivered', index=True)
    delivery_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)
    seen_at = Column(DateTime, default=datetime.now)
    last_delivered_at = Column(DateTime, default=datetime.now)
    handled_at = Column(DateTime)


class DailyQuota(Base):
    """每日配额表"""
    __tablename__ = 'daily_quota'

    id = Column(Integer, primary_key=True)
    date = Column(String(10), unique=True, nullable=False, index=True)  # YYYY-MM-DD

    comments_sent = Column(Integer, default=0)
    videos_analyzed = Column(Integer, default=0)
    runs_completed = Column(Integer, default=0)

    last_run_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.now)


class Database:
    """数据库管理器"""

    def __init__(self, db_path: str = "data/history.db"):
        """初始化数据库"""
        db_file = Path(db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)

        self.engine = create_engine(f'sqlite:///{db_path}', echo=False)
        Base.metadata.create_all(self.engine)
        # Lightweight SQLite migration for databases created by earlier versions.
        columns = {col['name'] for col in inspect(self.engine).get_columns('comments')}
        if 'parent_rpid' not in columns:
            with self.engine.begin() as connection:
                connection.execute(text('ALTER TABLE comments ADD COLUMN parent_rpid INTEGER'))
        if 'parent_content' not in columns:
            with self.engine.begin() as connection:
                connection.execute(text('ALTER TABLE comments ADD COLUMN parent_content TEXT'))
        if 'thread_root' not in columns:
            with self.engine.begin() as connection:
                connection.execute(text('ALTER TABLE comments ADD COLUMN thread_root INTEGER'))
        if 'target_user' not in columns:
            with self.engine.begin() as connection:
                connection.execute(text('ALTER TABLE comments ADD COLUMN target_user VARCHAR(100)'))
        session_columns = {
            col['name'] for col in inspect(self.engine).get_columns('agent_sessions')
        }
        if 'videos_json' not in session_columns:
            with self.engine.begin() as connection:
                connection.execute(text(
                    "ALTER TABLE agent_sessions ADD COLUMN videos_json TEXT DEFAULT '[]'"
                ))
        event_columns = {
            col['name'] for col in inspect(self.engine).get_columns('agent_events')
        }
        for name, ddl in (
            ('status', "ALTER TABLE agent_events ADD COLUMN status VARCHAR(20) DEFAULT 'delivered'"),
            ('delivery_count', "ALTER TABLE agent_events ADD COLUMN delivery_count INTEGER DEFAULT 0"),
            ('last_delivered_at', "ALTER TABLE agent_events ADD COLUMN last_delivered_at DATETIME"),
            ('handled_at', "ALTER TABLE agent_events ADD COLUMN handled_at DATETIME"),
        ):
            if name not in event_columns:
                with self.engine.begin() as connection:
                    connection.execute(text(ddl))

        Session = sessionmaker(bind=self.engine)
        self.session = Session()

        logger.info(f"数据库已初始化: {db_path}")

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

    def get_today_memory_event_count(self, event_type: str) -> int:
        start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        return self.session.query(MemoryEvent).filter(
            MemoryEvent.event_type == event_type,
            MemoryEvent.created_at >= start,
        ).count()

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

    def get_recent_videos(self, limit: int = 50) -> List[VideoRecord]:
        """获取最近的视频记录"""
        return self.session.query(VideoRecord)\
            .order_by(VideoRecord.created_at.desc())\
            .limit(limit)\
            .all()

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

    def get_comment_outcomes_since(self, since: datetime) -> List[Dict[str, Any]]:
        """Read success/failure outcomes since a timestamp (for style health)."""
        records = self.session.query(CommentRecord).filter(
            CommentRecord.created_at >= since
        ).all()
        return [
            {
                'success': bool(record.success),
                'error': record.error_message or '',
                'created_at': record.created_at,
            }
            for record in records
        ]

    def get_recent_comments(
        self, limit: int = 20, include_replies: bool = False
    ) -> List[Dict[str, Any]]:
        """获取最近发送的评论记录（可包含回复）"""
        query = self.session.query(CommentRecord)\
            .filter(CommentRecord.success == True)
        if not include_replies:
            query = query.filter(CommentRecord.comment_type == 'post')
        records = query.order_by(CommentRecord.created_at.desc())\
            .limit(limit)\
            .all()

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
        """关闭数据库连接"""
        self.session.close()
        self.engine.dispose()
        logger.info("数据库连接已关闭")
