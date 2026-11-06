"""Настроение рассказа (спокойное / весёлое / тревожное / динамичное) → фоновая музыка.

Угадывается тем же механизмом, что и сцена (SceneTracker): смысл последних слов + ключевые слова
+ подтверждение. Отличие одно: настроение есть всегда, с начала — default из moods.yaml.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from . import config
from .scenes import Scene, SceneTracker
from .textnorm import parse_pattern


def load_moods(path: Path = config.DATA_DIR / "moods.yaml") -> tuple[list[Scene], str]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    moods = [
        Scene(mid, m["music"], list(m.get("descriptions", [])), [parse_pattern(k) for k in m.get("keywords", [])])
        for mid, m in raw["moods"].items()
    ]
    default = raw.get("default", moods[0].id)
    if default not in {m.id for m in moods}:
        raise ValueError(f"moods.yaml: default={default!r} нет среди настроений")
    return moods, default


def make_mood_tracker(moods: list[Scene], default: str, embedder=None) -> SceneTracker:
    t = SceneTracker(list(moods), [], embedder=embedder)
    t.current = default
    return t
