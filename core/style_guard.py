"""发送前的“像真人”检查：避免重复开头、口头禅过载和梗复用。"""

import re

from loguru import logger

_CATCHPHRASES = ('哼', '才不是', '才没')
# 高频身体词：连着几条都在用，就成了模板
_BODY_WORDS = ('尾巴', '耳朵', '胸鳍')


def _normalize(text: str) -> str:
    return re.sub(r'\s+', '', str(text or '')).strip()


def _opener(text: str, length: int = 4) -> str:
    cleaned = str(text or '').strip().lstrip('“"「『（(')
    return cleaned[:length]


def find_style_issues(
    text: str, recent_comments: list, language_titles: list
) -> list:
    """返回这条内容相对最近发言的重复/模板化问题。"""
    text = str(text or '').strip()
    if not text:
        return []
    recent = [str(item or '').strip() for item in (recent_comments or []) if item]
    issues = []

    normalized = _normalize(text)
    if any(_normalize(item) == normalized for item in recent[:50]):
        issues.append('和最近发过的内容几乎一样')

    opener = _opener(text)
    if len(opener) >= 2:
        same = sum(
            1 for item in recent[:12] if _opener(item) == opener
        )
        if same >= 1:
            issues.append(f'开头“{opener}…”最近已经用过')

    for phrase in _CATCHPHRASES:
        if phrase not in text:
            continue
        window = recent[:20]
        usage = sum(1 for item in window if phrase in item)
        if window and usage / len(window) >= 0.5:
            issues.append(f'口头禅“{phrase}”最近出现得太频繁')

    for title in (language_titles or [])[:40]:
        title = str(title or '').strip()
        if len(title) < 2 or title not in text:
            continue
        if any(title in item for item in recent[:5]):
            issues.append(f'刚学到的“{title}”最近已经用过')

    for word in _BODY_WORDS:
        if word not in text:
            continue
        window = recent[:10]
        usage = sum(1 for item in window if word in item)
        if window and usage / len(window) >= 0.6:
            issues.append(f'“{word}”最近出现得太频繁')

    # 结尾模板：最近几条收尾用同一句话
    ending = normalized[-6:]
    if len(ending) >= 4 and any(
        _normalize(item)[-6:] == ending for item in recent[:5]
    ):
        issues.append('结尾和最近几条太像')

    if text.startswith('@'):
        at_rate = sum(1 for item in recent[:10] if item.startswith('@'))
        if at_rate >= 3:
            issues.append('最近几条都以 @ 开头，换一种开头')
    return issues


def _rewrite_prompt(text: str, issues: list, recent: list) -> str:
    samples = '\n'.join(
        f'{index + 1}. {item[:120]}' for index, item in enumerate(recent[:6])
    ) or '（暂无）'
    return (
        '把下面这条准备发到 B 站的内容改写得更像真人、更有她自己的特色，'
        '同时解决这些问题：\n- ' + '\n- '.join(issues) + '\n\n'
        f'她最近发过的内容（不要复用开头、梗或句式）：\n{samples}\n\n'
        f'原文：{text}\n\n'
        '要求：保留原文的具体信息和态度；句子长短不齐，允许口语和停顿；'
        '不要空泛夸赞，不要总结升华，不要解释，不要提“改写”这件事。'
        '如果原文 @ 了某人就保留。只输出改写后的正文，不要 JSON、引号或前后缀。'
    )


def clean_rewrite(response: str, original: str) -> str:
    """清洗模型改写结果；不可用时退回原文。"""
    text = str(response or '').strip()
    text = re.sub(r'^```.*?\n', '', text).strip()
    text = re.sub(r'\n```$', '', text).strip()
    text = text.strip('“”"「」『』')
    if not 4 <= len(text) <= 300:
        return original
    if any(marker in text for marker in ('改写：', '原文：', '{"', '"action"')):
        return original
    if original.count('@') and not text.count('@'):
        return original
    return text


async def prepare_outgoing_text(ai_client, db, config, text: str, purpose: str = 'comment') -> str:
    """发送前做一次重复检查；只有命中问题时才调用模型改写。"""
    text = str(text or '').strip()
    if not text or db is None or not config.get('evolution.anti_repetition', True):
        return text
    try:
        recent = db.get_recent_own_comments(limit=20)
        titles = [
            item['title'] for item in db.get_growth_items(
                kinds=['language'], limit=40
            )
        ]
    except Exception as exc:  # noqa: BLE001
        logger.debug(f'读取风格检查数据失败: {exc}')
        return text

    issues = find_style_issues(text, recent, titles)
    if not issues:
        return text
    if ai_client is None:
        return text
    logger.info(f'✍️ 发送前风格检查：{"；".join(issues)}')
    persona = ''
    try:
        from utils.persona_defaults import load_configured_persona
        persona = load_configured_persona(config, 800)
    except Exception:  # noqa: BLE001
        persona = ''
    try:
        response = await ai_client.chat(
            [
                {
                    'role': 'system',
                    'content': (
                        '你在帮一个角色把准备发送的内容改得更自然、更像真人。'
                        '只输出改写后的正文。'
                        + (f"\n她的角色设定：\n{persona}" if persona else '')
                    ),
                },
                {'role': 'user', 'content': _rewrite_prompt(text, issues, recent)},
            ],
            temperature=0.9,
            max_tokens=600,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug(f'风格改写失败: {exc}')
        return text
    rewritten = clean_rewrite(response or '', text)
    if rewritten != text:
        logger.debug(f'✍️ 已改写：{text[:40]!r} -> {rewritten[:40]!r} ({purpose})')
    return rewritten
