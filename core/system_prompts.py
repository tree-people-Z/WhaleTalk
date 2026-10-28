"""Load stable system-prompt sections from one editable file."""

from pathlib import Path
from typing import Dict


def _prompt_file() -> Path:
    return Path(__file__).resolve().parent.parent / 'assets' / 'system_prompt.md'


def _load_sections() -> Dict[str, str]:
    path = _prompt_file()
    try:
        text = path.read_text(encoding='utf-8')
    except OSError:
        return {}
    sections: Dict[str, str] = {}
    current = ''
    lines = []
    for line in text.splitlines():
        if line.startswith('## '):
            if current:
                sections[current] = '\n'.join(lines).strip()
            current = line[3:].strip()
            lines = []
        elif current:
            lines.append(line)
    if current:
        sections[current] = '\n'.join(lines).strip()
    return sections


def load_prompt(section: str, **values: str) -> str:
    text = _load_sections().get(section, '')
    for key, value in values.items():
        text = text.replace('{{' + key + '}}', str(value))
    return text
