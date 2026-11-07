"""Персонажи: звук при появлении в рассказе (медведь — рык, старик — кряхтение).

Наблюдатель находит упоминания; кто на сцене, решает модель мира (world.py, D-011):
«появился» — если его не было на сцене (впервые, ушёл — «заяц убежал», или давно молчали,
CHARACTER_REINTRO_S). Отрицание («медведя не было») — не упоминание.
Пересечения имён: длинное имя важнее («дед мороз» — мороз, не дед).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml

from . import config
from .actions import split_clauses
from .textnorm import Pattern, find_matches, is_negated, parse_pattern, tokenize
from .world import Mention, WorldState


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


def load_leave_words(path: Path = config.DATA_DIR / "characters.yaml") -> list[Pattern]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [parse_pattern(p) for p in raw.get("leave", [])]


@dataclass
class Appearance:
    character: Character
    word: str           # как назвали в тексте
    position: int       # номер слова во фразе


@dataclass
class CharacterTracker:
    """Наблюдатель: кого упомянули во фразе и уходит ли он. Кто на сцене — решает WorldState (D-011)."""
    characters: list[Character]
    clock: Callable[[], float] = None
    leave_words: list[Pattern] | None = None
    world: WorldState | None = None      # свой мир — для process() без движка (тесты, отладка)

    def __post_init__(self):
        # все имена всех персонажей, длинные и точные — первыми
        self._names = sorted(((p, c) for c in self.characters for p in c.names),
                             key=lambda pc: pc[0].specificity, reverse=True)
        if self.clock is None:
            import time
            self.clock = time.monotonic
        if self.leave_words is None:
            self.leave_words = load_leave_words()
        if self.world is None:
            self.world = WorldState(clock=self.clock)

    def observe(self, text: str) -> list[Mention]:
        """Финальная фраза → упоминания персонажей (первое на каждого), с пометкой «уходит»."""
        tokens = tokenize(text)
        leave_clauses = [(s, e) for s, e, _ in split_clauses(tokens)
                         if any(find_matches(p, tokens[s:e + 1]) for p in self.leave_words)]
        taken: set[int] = set()
        found: dict[str, Mention] = {}
        for pattern, ch in self._names:
            for m in find_matches(pattern, tokens):
                span = set(range(m.start, m.end + 1))
                if span & taken:
                    continue                 # слово уже занято более длинным именем
                taken |= span
                if is_negated(tokens, m.start, end=m.end) or _absent_after(tokens, m.end):
                    continue
                if ch.id not in found:
                    found[ch.id] = Mention(ch, tokens[m.start].word, m.start)
        mentions = sorted(found.values(), key=lambda m: m.position)
        for s, e in leave_clauses:
            inside = [m for m in mentions if s <= m.position <= e]
            if not inside:
                # «заяц испугался и убежал» — подлежащее не повторили: уходит последний названный до этой части
                before = [m for m in mentions if m.position < s]
                inside = before[-1:]
            for m in inside:
                m.leaving = True
        return mentions

    def process(self, text: str) -> list[Appearance]:
        """Удобство без движка: кто появился (по своему миру)."""
        mentions = {m.character.id: m for m in self.observe(text)}
        return [Appearance(mentions[c.id].character, c.word, mentions[c.id].position)
                for c in self.world.observe_characters(list(mentions.values())) if c.kind == "enter"]
