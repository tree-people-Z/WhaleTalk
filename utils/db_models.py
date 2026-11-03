"""SQLAlchemy ORM 模型（与 Database 分离，便于独立演进）。"""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.orm import declarative_base

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


class ObservedText(Base):
    """B 站上看到的公开文本，作为在线学习的原始素材。"""
    __tablename__ = 'observed_texts'

    id = Column(Integer, primary_key=True)
    digest = Column(String(64), unique=True, nullable=False, index=True)
    text = Column(Text)
    source = Column(String(40))
    seen_count = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.now, index=True)
    last_seen_at = Column(DateTime, default=datetime.now, index=True)


class GrowthItem(Base):
    """从在线观察中沉淀下来的成长条目（语言、兴趣、经验、知识、态度）。"""
    __tablename__ = 'growth_items'

    id = Column(Integer, primary_key=True)
    key = Column(String(120), unique=True, nullable=False, index=True)
    kind = Column(String(20), nullable=False, index=True)
    title = Column(String(80), nullable=False)
    content = Column(Text)
    example = Column(Text)
    source = Column(String(60))
    weight = Column(Integer, default=100)
    use_count = Column(Integer, default=0)
    enabled = Column(Boolean, default=True, index=True)
    last_used_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.now, index=True)
    last_seen_at = Column(DateTime, default=datetime.now)
