"""Персонажи: звук при появлении в рассказе (медведь — рык, старик — кряхтение).

Наблюдатель находит упоминания; кто на сцене, решает модель мира (world.py, D-011):
«появился» — если его не было на сцене (впервые, ушёл — «заяц убежал», или о нём молчали
CHARACTER_REINTRO_PHRASES фраз). Отрицание («медведя не было») и сравнение («как медведь») — не упоминание.
Обращение («ты, старый пёс») — не появление. После предлога («я у дедушки ушёл») — не тот, кто уходит.
Пересказ («рассказывал, как встретил волка») — не появление: о персонаже говорят, его нет на сцене.
Пересечения имён: длинное имя важнее («дед мороз» — мороз, не дед).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml

from . import config
from .actions import split_clauses
from .textnorm import Pattern, find_matches, is_comparison, is_negated, is_reported, parse_pattern, tokenize
from .world import Mention, WorldState


@dataclass
class Character:
    id: str
    sound: str
    names: list[Pattern]
    title: str = ""          # для людей: «Медведь», «Баба-яга» (каталог звуков, журнал)
    quiet_moods: tuple[str, ...] = ()   # в этих настроениях голос молчит: детский смех, когда ребёнка уносят гуси
    quiet_words: tuple[Pattern, ...] = ()   # с этими словами в фразе голос молчит сразу («подхватили мальчика»)
    voiced_by: tuple[str, ...] = ()         # звуки действий, которые и есть его голос (frost_crackle — Морозко)

    def is_quiet_in(self, text: str) -> bool:
        tokens = tokenize(text)
        return any(find_matches(p, tokens) for p in self.quiet_words)


def load_characters(path: Path = config.DATA_DIR / "characters.yaml") -> list[Character]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [Character(cid, c["sound"], [parse_pattern(n) for n in c["names"]], c.get("title", cid),
                      tuple(c.get("quiet_moods", ())), tuple(parse_pattern(w) for w in c.get("quiet_words", ())),
                      tuple(c.get("voiced_by", ())))
            for cid, c in raw["characters"].items()]


def _absent_after(tokens, end: int, window: int = 4) -> bool:
    """«медведя в лесу не было», «волка нигде нет» — персонажа нет. «медведь не спал» — есть."""
    after = [t.word for t in tokens[end + 1:end + 1 + window]]
    return "нет" in after or any(a == "не" and b.startswith("был") for a, b in zip(after, after[1:]))


def _is_address(tokens, start: int) -> bool:
    """«что ты наделал, старый пёс» — обращение к собеседнику: это не появление собаки."""
    before = tokens[max(0, start - config.ADDRESS_WINDOW): start]
    return any(t.word in config.ADDRESS_WORDS for t in before)


def load_leave_words(path: Path = config.DATA_DIR / "characters.yaml") -> list[Pattern]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [parse_pattern(p) for p in raw.get("leave", [])]


def load_leave_speakers(path: Path = config.DATA_DIR / "characters.yaml") -> set[str]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return set(raw.get("leave_speakers", []))


def load_leave_witness(path: Path = config.DATA_DIR / "characters.yaml") -> tuple[set[str], list[Pattern]]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")).get("leave_witness", {})
    return set(raw.get("before", [])), [parse_pattern(p) for p in raw.get("after", [])]


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
    leave_speakers: set[str] | None = None   # «я», «мы»…: уходит говорящий, а не названный ранее
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
        if self.leave_speakers is None:
            self.leave_speakers = load_leave_speakers()
        self._witness_before, self._witness_after = load_leave_witness()
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
                if is_negated(tokens, m.start, end=m.end) or _absent_after(tokens, m.end) \
                        or is_comparison(tokens, m.start) or is_reported(tokens, m.start):
                    continue                 # «медведя не было», «сильный, как медведь», «рассказывал про волка»
                new = Mention(ch, tokens[m.start].word, m.start,
                              obj=m.start > 0 and tokens[m.start - 1].word in config.OBJECT_PREPOSITIONS,
                              address=_is_address(tokens, m.start))
                old = found.get(ch.id)
                # одно упоминание на персонажа: прямое («лиса пришла») важнее косвенного («у лисы», «ты, лиса»)
                if old is None or ((old.obj or old.address) and not (new.obj or new.address)):
                    found[ch.id] = new
        mentions = sorted(found.values(), key=lambda m: m.position)
        for s, e in leave_clauses:
            in_clause = [m for m in mentions if s <= m.position <= e]
            # «я у дедушки ушёл» — дедушка дополнение (после «у»), уходит не он
            leaving = [m for m in in_clause if not m.obj and not m.address]
            speakers = [i for i in range(s, e + 1) if tokens[i].word in self.leave_speakers]
            if speakers:
                # «не ешь меня серый волк я от волка ушёл» (Vosk без запятых — одна часть фразы):
                # уходит «я»; персонаж может уходить, только если назван после «я» и не дополнением
                leaving = [m for m in leaving if m.position > speakers[-1]]
            elif not in_clause:
                # «заяц испугался и убежал» — подлежащее не повторили: уходит последний названный до этой части.
                # Но «я от волка ушёл» — уходит говорящий, волк остаётся.
                leaving = [m for m in mentions if m.position < s and not m.obj and not m.address][-1:]
                for m in leaving:
                    m.came_first = True
            for m in leaving:
                if not self._is_witness(tokens, m.position):
                    m.leaving = True
        return mentions

    def _is_witness(self, tokens, pos: int) -> bool:
        """«…укатился, только медведь его и видел» — медведь смотрит вслед, уходит не он."""
        if pos == 0 or tokens[pos - 1].word not in self._witness_before:
            return False
        after = tokens[pos + 1: pos + 4]
        return any(find_matches(p, after) for p in self._witness_after)

    def process(self, text: str) -> list[Appearance]:
        """Удобство без движка: кто появился (по своему миру)."""
        mentions = {m.character.id: m for m in self.observe(text)}
        return [Appearance(mentions[c.id].character, c.word, mentions[c.id].position)
                for c in self.world.observe_characters(list(mentions.values())) if c.kind == "enter"]
