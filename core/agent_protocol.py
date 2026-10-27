"""Shared JSON decision parser for the read-only and conversation agents."""

import json
import re
from typing import Any, Dict, Optional

_DSML_INVOKE = re.compile(
    r'<[|｜]DSML[|｜]\s*invoke\s+name=["\']([^"\']+)["\'][^>]*>(.*?)'
    r'</[|｜]DSML[|｜]\s*invoke>',
    re.S,
)
_DSML_PARAM = re.compile(
    r'<[|｜]DSML[|｜]\s*parameter\s+name=["\']([^"\']+)["\'][^>]*>(.*?)'
    r'</[|｜]DSML[|｜]\s*parameter>',
    re.S,
)


def parse_dsml_decision(text: str) -> Optional[Dict[str, Any]]:
    """Parse DeepSeek's native DSML tool-call markup into the agent protocol."""
    text = text or ''
    invoke = _DSML_INVOKE.search(text)
    if not invoke:
        return None
    tool = invoke.group(1).strip()
    body = invoke.group(2)
    params: Dict[str, Any] = {}
    method = ''
    for match in _DSML_PARAM.finditer(body):
        name = match.group(1).strip()
        value = match.group(2).strip()
        if name == 'method':
            method = value
            continue
        if name in ('arguments', 'params', 'parameters'):
            try:
                params = json.loads(value) if value else {}
            except (TypeError, ValueError):
                params = {'value': value}
        else:
            params[name] = value
    if tool == 'bili_api':
        if not isinstance(params, dict):
            params = {}
        return {
            'action': 'tool',
            'tool': 'bili_api',
            'arguments': {'method': method, 'arguments': params},
        }
    return {'action': 'tool', 'tool': tool, 'arguments': params}


def parse_json_decision(text: str) -> Optional[Dict[str, Any]]:
    text = (text or '').strip()
    if 'DSML' in text:
        # Native DeepSeek tool markup: never fall back to one of its JSON
        # parameter fragments as if it were a decision.
        return parse_dsml_decision(text)
    dsml = parse_dsml_decision(text)
    if dsml is not None:
        return dsml
    text = re.sub(r'^```(?:json)?', '', text).strip()
    text = re.sub(r'```$', '', text).strip()
    start, end = text.find('{'), text.rfind('}')
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None
