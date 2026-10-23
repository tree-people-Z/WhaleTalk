"""
双日记系统 - 增加趣味性
参考 dsh-bili-whale 项目
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
from loguru import logger


class DiarySystem:
    """双日记系统"""

    def __init__(self, diary_dir: Path = None):
        """
        初始化双日记系统

        Args:
            diary_dir: 日记存储目录
        """
        self.diary_dir = diary_dir or Path("data/diaries")
        self.diary_dir.mkdir(parents=True, exist_ok=True)

        # 两种日记的目录
        self.to_owner_dir = self.diary_dir / "to_owner"
        self.to_self_dir = self.diary_dir / "to_self"

        self.to_owner_dir.mkdir(parents=True, exist_ok=True)
        self.to_self_dir.mkdir(parents=True, exist_ok=True)

    def write_to_owner(
        self,
        content: str,
        videos_found: int = 0,
        videos_analyzed: int = 0,
        worthy_videos: list = None,
        comments_sent: int = 0,
        mood: str = "平静"
    ) -> Path:
        """
        写给主人的信（带情绪和细节的分享）

        Args:
            content: 日记内容（AI生成的带情绪的叙述）
            videos_found: 找到的视频数
            videos_analyzed: 分析的视频数
            worthy_videos: 值得关注的视频列表
            comments_sent: 发送的评论数
            mood: 当前心情

        Returns:
            日记文件路径
        """
        today = datetime.now()
        filename = f"{today.strftime('%Y-%m-%d')}_to_owner.md"
        filepath = self.to_owner_dir / filename

        worthy_videos = worthy_videos or []

        # 生成Markdown格式的日记
        diary_content = f"""# 给主人的信 💌

**日期**: {today.strftime('%Y年%m月%d日 %H:%M')}
**心情**: {mood}

---

## 今天的收获

{content}

---

## 数据统计

- 🔍 搜索到视频: **{videos_found}** 个
- 📊 深度分析: **{videos_analyzed}** 个
- ⭐ 值得关注: **{len(worthy_videos)}** 个
- 💬 发送评论: **{comments_sent}** 条

"""

        # 添加值得关注的视频列表
        if worthy_videos:
            diary_content += "## 今天发现的好视频\n\n"
            for i, video in enumerate(worthy_videos, 1):
                diary_content += f"### {i}. {video.get('title', '未知标题')}\n\n"
                diary_content += f"- 🔗 链接: https://www.bilibili.com/video/{video.get('bvid')}\n"
                diary_content += f"- 👤 UP主: {video.get('author', '未知')}\n"
                diary_content += f"- ⭐ 评分: {video.get('score', 0)}/20\n"
                diary_content += f"- 📝 推荐理由: {video.get('reason', '暂无')}\n\n"

        # 写入文件
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(diary_content)

        logger.info(f"📝 已写入给主人的信: {filepath}")
        return filepath

    def write_to_self(
        self,
        raw_data: Dict[str, Any],
        thoughts: Optional[str] = None
    ) -> Path:
        """
        写给自己的日记（不加滤镜的真实记录）

        Args:
            raw_data: 原始数据（JSON格式）
            thoughts: 内心想法（可选）

        Returns:
            日记文件路径
        """
        today = datetime.now()
        filename = f"{today.strftime('%Y-%m-%d')}_to_self.json"
        filepath = self.to_self_dir / filename

        diary_data = {
            'date': today.isoformat(),
            'timestamp': today.timestamp(),
            'raw_data': raw_data,
            'thoughts': thoughts
        }

        # 写入JSON文件
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(diary_data, f, indent=2, ensure_ascii=False)

        logger.info(f"📔 已写入给自己的日记: {filepath}")
        return filepath

    def get_recent_diaries(
        self,
        diary_type: str = "to_owner",
        days: int = 7
    ) -> list:
        """
        获取最近几天的日记

        Args:
            diary_type: 日记类型 ("to_owner" 或 "to_self")
            days: 天数

        Returns:
            日记文件路径列表
        """
        diary_dir = self.to_owner_dir if diary_type == "to_owner" else self.to_self_dir

        # 获取所有日记文件
        if diary_type == "to_owner":
            pattern = "*_to_owner.md"
        else:
            pattern = "*_to_self.json"

        files = sorted(diary_dir.glob(pattern), reverse=True)

        # 返回最近N天的日记
        return files[:days]

    def get_diary_summary(self, days: int = 7) -> Dict[str, Any]:
        """
        获取最近几天的日记摘要

        Args:
            days: 天数

        Returns:
            摘要信息
        """
        to_owner_files = self.get_recent_diaries("to_owner", days)
        to_self_files = self.get_recent_diaries("to_self", days)

        return {
            'to_owner_count': len(to_owner_files),
            'to_self_count': len(to_self_files),
            'to_owner_latest': to_owner_files[0] if to_owner_files else None,
            'to_self_latest': to_self_files[0] if to_self_files else None,
            'period': f"最近{days}天"
        }


if __name__ == "__main__":
    # 测试双日记系统
    diary = DiarySystem()

    # 写给主人的信
    test_videos = [
        {
            'bvid': 'BV1234567890',
            'title': '测试视频1',
            'author': '测试UP主',
            'score': 15,
            'reason': '内容有趣'
        }
    ]

    diary.write_to_owner(
        content="今天逛B站的时候，发现了一个特别有意思的视频！讲的是关于AI的最新进展，感觉主人会喜欢~",
        videos_found=50,
        videos_analyzed=10,
        worthy_videos=test_videos,
        comments_sent=2,
        mood="开心😊"
    )

    # 写给自己的日记
    diary.write_to_self(
        raw_data={
            'videos_found': 50,
            'videos_analyzed': 10,
            'worthy_count': 1,
            'run_time_seconds': 120
        },
        thoughts="今天运行很顺利，没有遇到错误"
    )

    # 获取摘要
    summary = diary.get_diary_summary(7)
    print("\n日记摘要:")
    for key, value in summary.items():
        print(f"  {key}: {value}")
