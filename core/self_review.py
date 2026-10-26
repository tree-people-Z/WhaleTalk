"""Weekly self-review and persona candidates.

This module never edits the live persona or code. It writes a review and a
candidate list for a human to inspect/apply.
"""

import datetime
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger


class SelfReview:
    def __init__(self, db, ai_client=None, diary_dir: Optional[Path] = None):
        self.db = db
        self.ai = ai_client
        self.review_dir = Path(diary_dir or Path('data') / 'diaries') / 'self_review'
        self.review_dir.mkdir(parents=True, exist_ok=True)
        self.candidates_path = Path('data') / 'persona_candidates.md'

    def last_review_path(self) -> Optional[Path]:
        files = sorted(self.review_dir.glob('*_self_review.md'), reverse=True)
        return files[0] if files else None

    def is_due(self, days: int = 7) -> bool:
        latest = self.last_review_path()
        if latest is None:
            return True
        age = datetime.datetime.now().timestamp() - latest.stat().st_mtime
        return age >= days * 86400

    def load_review_hints(self, max_chars: int = 700) -> str:
        """Return the actionable “next week” suggestions from the latest review."""
        path = self.last_review_path()
        if path is None:
            return ''
        try:
            text = path.read_text(encoding='utf-8')
        except OSError:
            return ''
        marker = '## 下周建议'
        if marker in text:
            section = text.split(marker, 1)[1]
            section = section.split('\n## ', 1)[0]
        else:
            section = text
        return section.strip()[:max_chars]

    @staticmethod
    def read_candidates(candidates_path: Optional[Path] = None) -> str:
        path = Path(candidates_path or (Path('data') / 'persona_candidates.md'))
        if not path.is_file():
            return ''
        try:
            return path.read_text(encoding='utf-8').strip()
        except OSError:
            return ''

    @staticmethod
    def apply_candidates_to_persona(
        persona_path: Optional[Path] = None,
        candidates_path: Optional[Path] = None,
    ) -> Path:
        """Append confirmed candidates to the persona with a timestamped backup."""
        persona = Path(persona_path or (Path('data') / 'persona.md'))
        candidates = SelfReview.read_candidates(candidates_path)
        if not persona.is_file():
            raise RuntimeError('找不到 data/persona.md')
        if not candidates or '暂无' in candidates and len(candidates) < 80:
            raise RuntimeError('没有可应用的人设候选')
        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        backup = persona.with_name(persona.name + f'.bak-{stamp}')
        shutil.copy2(persona, backup)
        with persona.open('a', encoding='utf-8') as stream:
            stream.write(
                f"\n\n## 自复盘候选（人工确认 {datetime.date.today().isoformat()}）\n"
                f"{candidates}\n"
            )
        logger.info(f'已应用人设候选，备份: {backup}')
        return backup

    def _recent_diaries(self) -> List[str]:
        base = self.review_dir.parent
        texts = []
        for path in sorted(base.glob('to_owner/*_to_owner.md'), reverse=True)[:3]:
            try:
                texts.append(path.read_text(encoding='utf-8')[:2500])
            except OSError:
                continue
        return texts

    def _build_prompt(self) -> str:
        stats = self.db.get_statistics()
        events = self.db.get_recent_memory_events(limit=80)
        comments = self.db.get_recent_comments(limit=40, include_replies=True)
        event_lines = []
        for event in events[-30:]:
            who = event.get('user_name') or '网友'
            said = (event.get('content') or '').replace('\n', ' ')[:100]
            mine = (event.get('my_content') or '').replace('\n', ' ')[:100]
            if said or mine:
                event_lines.append(f"- {who} 说：{said} / 我回：{mine}")
        comment_lines = [
            (item.get('content') or '').replace('\n', ' ')[:100]
            for item in comments[:20]
        ]
        diaries = self._recent_diaries()
        return f"""你是鲸语（鲸鱼娘）的运营复盘助手。请根据下面真实数据做一次每周复盘。

# 数据
统计：今日发送 {stats.get('today_comments', 0)} 条（评论 {stats.get('today_posts', 0)} / 回复 {stats.get('today_replies', 0)}）；
本周互动事件 {len(events)} 条；最近评论/回复 {len(comments)} 条。

最近互动：
{chr(10).join(event_lines) or '（暂无）'}

最近评论：
{chr(10).join('- ' + line for line in comment_lines) or '（暂无）'}

最近日记：
{chr(10).join(diaries) or '（暂无）'}

# 要求
1. 只复盘表达方式、互动节奏、话题偏好，不要建议改代码或突破平台限制。
2. 核心人设、Claude 身份底线、称呼规则不可改。
3. 指出哪些话像模板/像客服/过于重复，给出更自然的替代表达。
4. 输出 Markdown，包含：
## 本周表现
## 有效的表达
## 机械感与风险
## 下周建议
## 人设候选调整（最多3条，必须人工确认）
不要编造数据；没有数据就写“暂无”。"""

    async def generate(self) -> Dict[str, Any]:
        prompt = self._build_prompt()
        text = ''
        if self.ai is not None:
            try:
                text = await self.ai.chat(
                    [
                        {'role': 'system', 'content': '你是严谨的运营复盘助手，只基于给出的数据写复盘。'},
                        {'role': 'user', 'content': prompt},
                    ],
                    temperature=0.4,
                    max_tokens=1600,
                ) or ''
            except Exception as exc:  # noqa: BLE001
                logger.warning(f'AI 自我复盘失败，使用本地摘要: {exc}')
        if not text.strip():
            text = self._fallback_review()
        today = datetime.datetime.now().strftime('%Y-%m-%d')
        review_path = self.review_dir / f'{today}_self_review.md'
        review_path.write_text(
            f'# 鲸语自我复盘 {today}\n\n> 自动生成，仅作建议；不会自动修改人设。\n\n{text}\n',
            encoding='utf-8',
        )
        candidates = self._extract_candidates(text)
        self.candidates_path.write_text(
            f'# 人设候选调整 {today}\n\n'
            '> 未自动应用。确认后再手动修改 `data/persona.md`。\n\n'
            f'{candidates}\n',
            encoding='utf-8',
        )
        logger.info(f'自我复盘已写入: {review_path}')
        return {
            'review_path': str(review_path),
            'candidates_path': str(self.candidates_path),
            'text': text,
        }

    def _fallback_review(self) -> str:
        stats = self.db.get_statistics()
        events = self.db.get_recent_memory_events(limit=80)
        return (
            '## 本周表现\n'
            f'- 今日发送 {stats.get("today_comments", 0)} 条（评论 {stats.get("today_posts", 0)} / 回复 {stats.get("today_replies", 0)}）。\n'
            f'- 最近记录互动 {len(events)} 条。\n\n'
            '## 有效的表达\n- 暂无足够数据，下周继续积累。\n\n'
            '## 机械感与风险\n- 注意不要连续使用同一个傲娇开头，也不要对每条评论都秒回。\n\n'
            '## 下周建议\n- 优先回复认识的人和自己视频下的评论；评论长度保持 20–50 字。\n\n'
            '## 人设候选调整（最多3条，必须人工确认）\n- 暂无。\n'
        )

    @staticmethod
    def _extract_candidates(text: str) -> str:
        marker = '## 人设候选调整'
        if marker in text:
            return text.split(marker, 1)[1].strip()
        return '- 暂无。'
