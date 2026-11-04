"""Shared JSON decision parser for the read-only and conversation agents."""

import json
import re
from typing import Any, Dict, Optional

# The model sometimes duplicates the pipe character (`<｜｜DSML｜｜>`), so every
# marker position accepts one or more of either pipe variant.
_DSML_INVOKE = re.compile(
    r'<[|｜]+DSML[|｜]+\s*invoke\s+name=["\']([^"\']+)["\'][^>]*>(.*?)'
    r'</[|｜]+DSML[|｜]+\s*invoke[^>]*>',
    re.S,
)
# Closing tags may carry attributes that belong to the next parameter, e.g. the
# model writes `parameter name="comments" string="false">10` where only the tag
# name should appear. Allow trailing attributes so one bad tag cannot swallow
# the whole following parameter into the previous value.
_DSML_PARAM = re.compile(
    r'<[|｜]+DSML[|｜]+\s*parameter\s+name=["\']([^"\']+)["\'][^>]*>(.*?)'
    r'</[|｜]+DSML[|｜]+\s*parameter[^>]*>',
    re.S,
)
# Any leftover markup inside a single value (opening tag, closing tag, or the
# fragment left over when the model pastes markup into an argument).
_DSML_MARKUP = re.compile(r'</?[|｜]+DSML[|｜]+[^>]*>?')
_DSML_MARKUP_START = re.compile(r'</?[|｜]*DSML[|｜]*')
# Keys that make a parsed dict an actual agent decision.  A bare JSON object
# harvested out of tool markup (`{}` or `{"keyword": "x"}`) has none of them.
_DECISION_KEYS = frozenset(
    {'action', 'tool', 'name', 'method', 'method_name', 'api', 'arguments', 'params', 'args', 'input'}
)
_BVID = re.compile(r'BV[0-9A-Za-z]{10}')
_NON_BILI_TOOLS = {'inspect_video', 'read_diary', 'write_diary'}


def strip_tool_markup(value: Any) -> str:
    """Drop leaked tool-call markup from one model-provided value."""
    text = str(value if value is not None else '')
    start = _DSML_MARKUP_START.search(text)
    if start:
        # Everything from the stray tag onward belongs to markup, not to the value.
        text = text[:start.start()]
    return _DSML_MARKUP.sub('', text).strip()


def normalize_bvid(value: Any) -> str:
    """Return the first well-formed BV id inside a model-provided value."""
    match = _BVID.search(strip_tool_markup(value))
    return match.group(0) if match else ''


def sanitize_arguments(value: Any) -> Any:
    """Recursively clean parsed argument values and normalize BV ids."""
    if isinstance(value, str):
        return strip_tool_markup(value)
    if isinstance(value, list):
        return [sanitize_arguments(item) for item in value]
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            item = sanitize_arguments(item)
            if key == 'bvid' and isinstance(item, str):
                item = normalize_bvid(item) or item
            cleaned[key] = item
        return cleaned
    return value


def _clean_value(value: str) -> str:
    return strip_tool_markup(value).strip('"').strip('}').strip()


def _clean_params(params: Dict[str, Any]) -> Dict[str, Any]:
    cleaned = sanitize_arguments(params)
    return cleaned if isinstance(cleaned, dict) else {}


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
                params = {'value': strip_tool_markup(value)}
        else:
            params[name] = _clean_value(value)
    params = _clean_params(params)
    if tool == 'bili_api':
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
    if _DSML_INVOKE.search(text):
        # Native DeepSeek tool markup: never fall back to one of its JSON
        # parameter fragments as if it were a decision.  A garbled/decorated
        # marker (e.g. `<｜｜DSML｜｜>`) therefore fails via the decision-key
        # validation below instead of silently turning `{}` into a decision.
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
    if not isinstance(data, dict):
        return None
    if not _DECISION_KEYS.intersection(data):
        # Leftover markup fragments (`{}`, `{"keyword": ...}`) are not decisions.
        return None
    return sanitize_arguments(data)
