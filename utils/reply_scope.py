"""Reply-scope presets.

User-facing choices are intentionally simple:
- owner: only the configured owner
- all: all interactions directed at the bot, interesting comments, whale
  greetings and requested-video visits (still bounded by quotas/cooldowns)
"""

from typing import Any

REPLY_SCOPE_OWNER = 'owner'
REPLY_SCOPE_ALL = 'all'

_SCOPE_VALUES = {
    REPLY_SCOPE_OWNER: {
        'reply_only_owner': True,
        'reply_to_others': False,
        'reply_interesting_comments': False,
        'reply_own_video_comments': False,
        'comment_requested_video': False,
        'greet_other_whales': False,
    },
    REPLY_SCOPE_ALL: {
        'reply_only_owner': False,
        'reply_to_others': True,
        'reply_interesting_comments': True,
        'reply_own_video_comments': True,
        'comment_requested_video': True,
        'greet_other_whales': True,
    },
}


def resolve_reply_scope(config: Any) -> str:
    scope = config.get('interaction.reply_scope', '')
    if scope in _SCOPE_VALUES:
        return scope
    # Migrate older configs: default to all unless owner-only was explicit.
    if config.get('interaction.reply_only_owner', False):
        return REPLY_SCOPE_OWNER
    return REPLY_SCOPE_ALL


def apply_reply_scope(config: Any, scope: str) -> None:
    scope = scope if scope in _SCOPE_VALUES else REPLY_SCOPE_ALL
    config.set('interaction.reply_scope', scope)
    for key, value in _SCOPE_VALUES[scope].items():
        config.set(f'interaction.{key}', value)
