"""Reply-scope presets.

- owner: only the configured owner
- all: every reply/@/own-video comment directed at the bot
"""

from typing import Any

REPLY_SCOPE_OWNER = 'owner'
REPLY_SCOPE_ALL = 'all'
_SCOPES = {REPLY_SCOPE_OWNER, REPLY_SCOPE_ALL}


def resolve_reply_scope(config: Any) -> str:
    scope = config.get('interaction.reply_scope', '')
    if scope in _SCOPES:
        return scope
    # Migrate old configs: default to all unless owner-only was explicit.
    if config.get('interaction.reply_only_owner', False):
        return REPLY_SCOPE_OWNER
    return REPLY_SCOPE_ALL


def apply_reply_scope(config: Any, scope: str) -> None:
    config.set(
        'interaction.reply_scope',
        scope if scope in _SCOPES else REPLY_SCOPE_ALL,
    )
