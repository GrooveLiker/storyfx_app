"""Персонажи: звук при появлении в рассказе (медведь — рык, старик — кряхтение).

«Появление» = первое упоминание или упоминание после долгого молчания о персонаже
(CHARACTER_REINTRO_S). Отрицание («медведя не было») — не появление.
Пересечения имён: длинное имя важнее («дед мороз» — мороз, не дед).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import yaml

from . import config
from .textnorm import Pattern, find_matches, is_negated, parse_pattern, tokenize


@dataclass
class Character:
    id: str
    sound: str
    names: list[Pattern]
    title: str = ""          # для людей: «Медведь», «Баба-яга» (каталог звуков, журнал)


def load_characters(path: Path = config.DATA_DIR / "characters.yaml") -> list[Character]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [Character(cid, c["sound"], [parse_pattern(n) for n in c["names"]], c.get("title", cid))
            for cid, c in raw["characters"].items()]


def _absent_after(tokens, end: int, window: int = 4) -> bool:
    """«медведя в лесу не было», «волка нигде нет» — персонажа нет. «медведь не спал» — есть."""
    after = [t.word for t in tokens[end + 1:end + 1 + window]]
    return "нет" in after or any(a == "не" and b.startswith("был") for a, b in zip(after, after[1:]))


@dataclass
class Appearance:
    character: Character
    word: str           # как назвали в тексте
    position: int       # номер слова во фразе


@dataclass
class CharacterTracker:
    characters: list[Character]
    clock: Callable[[], float] = None
    _last_seen: dict[str, float] = field(default_factory=dict)

    def __post_init__(self):
        # все имена всех персонажей, длинные и точные — первыми
        self._names = sorted(((p, c) for c in self.characters for p in c.names),
                             key=lambda pc: pc[0].specificity, reverse=True)
        if self.clock is None:
            import time
            self.clock = time.monotonic

    def process(self, text: str) -> list[Appearance]:
        """Финальная фраза → персонажи, которые в ней появились (по порядку в тексте)."""
        tokens = tokenize(text)
        taken: set[int] = set()
        found: dict[str, Appearance] = {}
        mentioned: set[str] = set()
        for pattern, ch in self._names:
            for m in find_matches(pattern, tokens):
                span = set(range(m.start, m.end + 1))
                if span & taken:
                    continue                 # слово уже занято более длинным именем
                taken |= span
                if is_negated(tokens, m.start, end=m.end) or _absent_after(tokens, m.end):
                    continue
                mentioned.add(ch.id)
                if ch.id not in found:
                    found[ch.id] = Appearance(ch, tokens[m.start].word, m.start)
        now = self.clock()
        new = [a for cid, a in found.items()
               if now - self._last_seen.get(cid, float("-inf")) >= config.CHARACTER_REINTRO_S]
        for cid in mentioned:
            self._last_seen[cid] = now       # любое упоминание продлевает «присутствие»
        return sorted(new, key=lambda a: a.position)[:config.MAX_CHARACTERS_PER_PHRASE]
