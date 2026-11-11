"""Compact old diary files into short entries.

每条日记原来按“每轮一条”堆积，一天能写到几万字，进上下文时把语气材料挤掉。
这个脚本把每天的记录压缩成 250–450 字的日记载（保留发布/主人互动/学到的/情绪，
删掉逐轮视频清单、评分、次数、审计行），原文先备份。

用法：
    python tools/compact_diaries.py --dry-run --only 2026-11-09
    python tools/compact_diaries.py --only 2026-11-09
    python tools/compact_diaries.py            # 处理全部
"""

import argparse
import asyncio
import re
import zipfile
from datetime import datetime
from pathlib import Path

from utils.config_manager import ConfigManager
from utils.secure_store import unprotect

HEADER = re.compile(r'^## .*$', re.M)
NOISE_PREFIXES = ('审计：', '这轮写操作', '写操作')
KEEP_HINTS = (
    '主人', '发布', '投稿', '拍', '学到', '记住', '第一次', '被夸', '被说',
    '日记', '重要', '决定了', '明白',
)
# 每晚重复的固定桥段，除非当天真和主人有来往，否则不进素材
BOILERPLATE = ('白饭', '别熬', '催睡', '吃饭', '热了吃', '去睡', '晚安')
EVENT_WORDS = ('夸', '说', '批评', '拍', '发布', '投', '问', '聊')
ENDING = ('。', '！', '？', '…', '”', '」')
MAX_BULLETS = 30
BULLET_CLIP = 130

PROMPT = """把下面这一天「鲸鱼娘」的日记原始记录，压缩成一篇 250–450 字的日记载。

要求：
1. 用她自己的第一人称和语气：短句、口语，可以有点傲娇，但不要用固定的开头和结尾。
2. 保留：拍片/发布及结果、和主人有关的互动、学到的东西、情绪转折、一两个值得记住的具体细节。
3. 删掉：逐轮的视频清单与评分、播放数、帧数、时长、写操作次数、审计行、例行巡视。
4. 不要每晚都写催睡和白饭，除非当天和主人真聊过。
5. 不要编造事实，不要加标题、列表符号或代码块，只输出正文（可分成 2–4 个短段落）。
"""


def _clean_line(line: str) -> str:
    text = line.strip()
    if text.startswith(('- ', '* ')):
        text = text[2:].strip()
    return text


def digest(text: str) -> str:
    """把一天原文压成给模型看的素材：保留叙述句和高价值要点。"""
    blocks = [block for block in HEADER.split(text) if block.strip()]
    prose = []
    bullets = []
    for block in blocks:
        for raw in block.splitlines():
            line = raw.strip()
            if not line:
                continue
            cleaned = _clean_line(line)
            if cleaned.startswith(NOISE_PREFIXES):
                continue
            if (any(word in cleaned for word in BOILERPLATE)
                    and not any(word in cleaned for word in EVENT_WORDS)):
                continue
            if line.startswith(('- ', '* ')):
                if any(hint in cleaned for hint in KEEP_HINTS):
                    bullets.append(cleaned[:BULLET_CLIP])
            else:
                prose.append(cleaned)
    seen = set()
    unique_prose = []
    for line in prose:
        key = line[:10]
        if key in seen:
            continue
        seen.add(key)
        unique_prose.append(line)
    return chr(10).join(unique_prose + [f'- {item}' for item in bullets[:MAX_BULLETS]])


def memory_events(day: str, memory_file: Path) -> str:
    """长期记忆里当天的事件，作为压缩时的事实参考。"""
    try:
        text = memory_file.read_text(encoding='utf-8')
    except OSError:
        return ''
    lines = [
        line.strip() for line in text.splitlines()
        if line.strip().startswith(f'- {day}')
    ]
    return chr(10).join(lines[:6])


def build_client(config: ConfigManager):
    from core.ai_client import AIClient

    return AIClient(
        provider=config.get('ai.provider', 'openai'),
        api_key=unprotect(config.get('ai.api_key', '')),
        model=config.get('ai.model'),
        base_url=config.get('ai.base_url'),
        timeout=180,
        max_retries=2,
        max_output_tokens=8000,
    )


async def summarize(client, material: str, date_name: str) -> str:
    prompt = PROMPT + chr(10) + '# 日期' + chr(10) + date_name + chr(10) * 2 \
        + '# 原始记录' + chr(10) + material
    messages = [
        {'role': 'system', 'content': '你是一个只做压缩、不做创作的编辑。'},
        {'role': 'user', 'content': prompt},
    ]
    budget = 4000
    parts = []
    for _ in range(3):
        text = (await client.chat(
            messages, temperature=0.4, max_tokens=budget
        ) or '').strip()
        if text:
            parts.append(text)
        joined = ''.join(parts).strip()
        if joined and joined[-1] in ENDING and len(joined) >= 120:
            return joined
        if text:
            # 被推理吃掉预算时会半句断掉：接着写，不要从头重来
            messages = messages[:2] + [
                {'role': 'assistant', 'content': text},
                {'role': 'user', 'content': '上面这段被截断了，请接着写完剩下的部分，只输出续写内容。'},
            ]
        budget = min(12000, budget * 2)
    return ''.join(parts).strip()


def backup(files, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    archive = backup_dir / f'diaries-{stamp}.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            zf.write(path, arcname=f'to_owner/{path.name}')
    return archive


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--only', default='')
    parser.add_argument('--dir', default=str(Path('data') / 'diaries' / 'to_owner'))
    args = parser.parse_args()

    diary_dir = Path(args.dir)
    files = sorted(diary_dir.glob('*.md'))
    if args.only:
        files = [path for path in files if path.name.startswith(args.only)]
    if not files:
        print('没有需要处理的日记')
        return 1

    config = ConfigManager(Path('data') / 'config.json')
    client = build_client(config)
    memory_file = Path('data') / 'memory.md'

    if not args.dry_run:
        archive = backup(files, diary_dir.parent / 'backup')
        print(f'已备份 {len(files)} 个文件 -> {archive}')

    total_before = total_after = 0
    for path in files:
        original = path.read_text(encoding='utf-8')
        material = digest(original)
        events = memory_events(path.stem, memory_file)
        if events:
            material = ('# 长期记忆里当天的事件（事实参考）' + chr(10) + events
                        + chr(10) * 2 + '# 当天原始记录' + chr(10) + material)
        summary = await summarize(client, material, path.stem)
        total_before += len(original)
        if not summary:
            print(f'{path.name}: 压缩失败，保留原文')
            total_after += len(original)
            continue
        output = f'## {path.stem}' + chr(10) * 2 + summary.strip() + chr(10)
        total_after += len(output)
        print(f'{path.name}: {len(original)} -> {len(output)} 字')
        if args.dry_run:
            print('---')
            print(output)
            print('---')
        else:
            path.write_text(output, encoding='utf-8')
    print(f'合计 {total_before} -> {total_after} 字')
    return 0


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
