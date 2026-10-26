"""Shared probability helper for human-like actions."""

import random
from typing import Any


def roll_probability(config: Any, key: str, default: float) -> bool:
    """Return True when a 0-100 percentage setting fires.

    `key` is relative to the `interaction` section.
    """
    try:
        probability = float(config.get(f'interaction.{key}', default))
    except (TypeError, ValueError):
        probability = default
    probability = max(0.0, min(100.0, probability))
    return random.random() * 100 < probability
