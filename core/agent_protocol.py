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
_NON_BILI_TOOLS = {'inspect_video', 'read_diary', 'write_diary'}


def _clean_value(value: str) -> str:
    return str(value or '').strip().strip('"').strip('}').strip().strip('"')


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
            method = _clean_value(value)
            continue
        if name in ('arguments', 'params', 'parameters'):
            try:
                params = json.loads(value) if value else {}
            except (TypeError, ValueError):
                params = {'value': value}
        else:
            params[name] = _clean_value(value)
    if tool == 'bili_api':
        if not isinstance(params, dict):
            params = {}
        nested_method = _clean_value(params.get('method', ''))
        nested_args = params.get('arguments')
        if nested_method:
            params.pop('method', None)
            if nested_method in _NON_BILI_TOOLS:
                return {
                    'action': 'tool',
                    'tool': nested_method,
                    'arguments': nested_args if isinstance(nested_args, dict) else params,
                }
            return {
                'action': 'tool',
                'tool': 'bili_api',
                'arguments': {
                    'method': nested_method,
                    'arguments': nested_args if isinstance(nested_args, dict) else params,
                },
            }
        tool_param = _clean_value(params.pop('tool', ''))
        if not method and tool_param:
            if tool_param in _NON_BILI_TOOLS:
                return {'action': 'tool', 'tool': tool_param, 'arguments': params}
            return {'action': 'tool', 'tool': 'bili_api', 'arguments': {'method': tool_param, 'arguments': params}}
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
