"""
数据库模块
使用SQLite存储历史记录
"""

from pathlib import Path
from datetime import datetime
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

    comment_type = Column(String(20))  # 'post'=发出, 'reply'=回复
    content = Column(Text)
    target_user = Column(String(100))  # 回复的用户

    success = Column(Boolean)
    error_message = Column(Text)

    created_at = Column(DateTime, default=datetime.now)


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
        parent_rpid: Optional[int] = None
    ) -> CommentRecord:
        """添加评论记录"""
        record = CommentRecord(
            bvid=bvid,
            aid=aid,
            rpid=rpid,
            parent_rpid=parent_rpid,
            comment_type=comment_type,
            content=content,
            success=success,
            error_message=error_message
        )

        self.session.add(record)
        self.session.commit()
        return record

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

    def get_recent_videos(self, limit: int = 50) -> List[VideoRecord]:
        """获取最近的视频记录"""
        return self.session.query(VideoRecord)\
            .order_by(VideoRecord.created_at.desc())\
            .limit(limit)\
            .all()

    def get_recent_comments(self, limit: int = 20) -> List[Dict[str, Any]]:
        """获取最近发送的评论记录"""
        records = self.session.query(CommentRecord)\
            .filter(CommentRecord.comment_type == 'post', CommentRecord.success == True)\
            .order_by(CommentRecord.created_at.desc())\
            .limit(limit)\
            .all()

        results = []
        for record in records:
            video = self.session.query(VideoRecord).filter_by(bvid=record.bvid).first()
            results.append({
                'aid': record.aid,
                'bvid': record.bvid,
                'rpid': record.rpid,
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
        total_comments = self.session.query(VideoRecord)\
            .filter_by(commented=True).count()

        today_quota = self.get_today_quota()

        return {
            'total_videos_analyzed': total_videos,
            'total_comments_sent': total_comments,
            'today_comments': today_quota.comments_sent,
            'today_videos': today_quota.videos_analyzed,
            'today_runs': today_quota.runs_completed
        }

    def close(self):
        """关闭数据库连接"""
        self.session.close()
        self.engine.dispose()
        logger.info("数据库连接已关闭")
