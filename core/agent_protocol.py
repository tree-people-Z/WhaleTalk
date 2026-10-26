"""Shared JSON decision parser for the read-only and conversation agents."""

import json
import re
from typing import Any, Dict, Optional


def parse_json_decision(text: str) -> Optional[Dict[str, Any]]:
    text = (text or '').strip()
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
