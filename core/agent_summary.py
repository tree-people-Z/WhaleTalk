"""Agent 轮次结束后的总结校验与上下文压缩。"""

import re

from loguru import logger

# 较早的工具结果压缩后保留的字符数
COMPACT_RESULT_LIMIT = 600
# 始终完整保留最近 N 条工具结果
KEEP_RECENT_RESULTS = 4
_TOOL_PREFIX = '工具结果：'


def parse_model_audit(summary: str) -> dict:
    """解析模型自己报告的评分/@ 审计，只记录，不干预。"""
    text = str(summary or '')
    audit = {}
    score = re.search(r'最高分\s*[:：]?\s*(\d{1,2})\s*(?:/|／)\s*20', text)
    if score:
        audit['max_score'] = int(score.group(1))
    mention = re.search(r'@\s*主人\s*[:：]?\s*(是|否|已|未)', text)
    if mention:
        audit['mentioned_owner'] = mention.group(1) in {'是', '已'}
    return audit


def summary_mismatch(summary: str, actions: list) -> list:
    """找出模型声称做过、但本轮实际没有成功的动作。"""
    actual = '；'.join(actions)
    claims = [
        ('点赞', ('点赞', '点了赞', '给了.*赞', '赞了'), ('点赞',)),
        ('收藏', ('收藏',), ('收藏',)),
        ('评论/留言', ('留言', '评论了', '留了评论', '发了评论', '回复了', '回了'),
         ('发送评论',)),
        ('私信', ('发送私信', '发了私信', '回了私信', '回复.{0,6}私信', '私信.{0,6}(回|发)'),
         ('发送私信',)),
        ('关注', ('关注',), ('关注',)),
        ('弹幕', ('弹幕',), ('发送弹幕',)),
    ]
    missing = []
    for claim, patterns, markers in claims:
        if not any(re.search(pattern, summary) for pattern in patterns):
            continue
        if not any(marker in actual for marker in markers):
            missing.append(claim)
    return missing


def log_actions(actions: list) -> None:
    if actions:
        logger.info('🐋 本轮动作：' + '；'.join(actions))
    else:
        logger.info('🐋 本轮动作：没有调用工具')


def compact_tool_results(
    messages: list,
    keep_recent: int = KEEP_RECENT_RESULTS,
    limit: int = COMPACT_RESULT_LIMIT,
) -> int:
    """压缩较早的工具结果，控制长对话的 token 成本。

    只保留最近 ``keep_recent`` 条完整结果，其余截断为 ``limit`` 个字符。
    返回被压缩的条数。
    """
    indices = [
        index for index, message in enumerate(messages)
        if message.get('role') == 'user'
        and str(message.get('content') or '').startswith(_TOOL_PREFIX)
    ]
    if len(indices) <= keep_recent:
        return 0
    compacted = 0
    for index in indices[:-keep_recent] if keep_recent else indices:
        content = str(messages[index].get('content') or '')
        if len(content) <= limit:
            continue
        messages[index] = {
            **messages[index],
            'content': content[:limit] + '\n…（较早的工具结果已压缩）',
        }
        compacted += 1
    return compacted
