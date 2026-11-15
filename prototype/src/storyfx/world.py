"""Модель мира (звено 2, D-011): где мы, погода, кто на сцене, настроение — одно состояние на всех.

Наблюдатели (сцена, персонажи, настроение, действия) сообщают, что услышали; решает мир.
Изменения мира (WorldChange) читает звукорежиссёр (engine.py) и решает, что звучит.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Callable

from . import config


@dataclass(frozen=True)
class WorldChange:
    kind: str           # place | weather_on | weather_off | enter | leave | mood | action
    id: str
    reason: str = ""
    word: str = ""      # как назвали в тексте (персонажи)


@dataclass
class Mention:
    """Персонаж упомянут во фразе. leaving — в той же части фразы глагол ухода («заяц убежал»)."""
    character: object   # characters.Character
    word: str
    position: int
    leaving: bool = False
    obj: bool = False       # после предлога: «я у дедушки ушёл» — дедушка не уходит
    address: bool = False   # обращение: «что ты наделал, старый пёс» — не появление собаки


@dataclass
class WorldState:
    clock: Callable[[], float]
    place: str | None = None
    weather: list[str] = field(default_factory=list)
    mood: str | None = None
    present: dict[str, int] = field(default_factory=dict)       # персонаж → номер фразы, где последний раз упомянут
    phrase: int = 0                                             # сколько фраз с персонажами уже прошло
    history: deque = field(default_factory=lambda: deque(maxlen=200))

    def _record(self, ch: WorldChange) -> WorldChange:
        self.history.append((self.clock(), ch))
        return ch

    # ---------- место, погода, настроение ----------
    def set_place(self, place: str, reason: str = "") -> list[WorldChange]:
        if place == self.place:
            return []
        self.place = place
        return [self._record(WorldChange("place", place, reason))]

    def set_weather(self, active: list[str], changes: list[tuple[str, bool, str]]) -> list[WorldChange]:
        self.weather = list(active)
        return [self._record(WorldChange("weather_on" if on else "weather_off", wid, reason))
                for wid, on, reason in changes]

    def set_mood(self, mood: str, reason: str = "") -> list[WorldChange]:
        if mood == self.mood:
            return []
        self.mood = mood
        return [self._record(WorldChange("mood", mood, reason))]

    def action(self, sfx: str, reason: str = "") -> WorldChange:
        return self._record(WorldChange("action", sfx, reason))

    # ---------- персонажи ----------
    def is_present(self, cid: str) -> bool:
        """На сцене — пока не ушёл и о нём говорили не больше CHARACTER_REINTRO_PHRASES фраз назад.
        По фразам, а не по секундам: таймер «90 с» срабатывал посреди сказки и при медленном наборе."""
        seen = self.present.get(cid)
        return seen is not None and self.phrase - seen < config.CHARACTER_REINTRO_PHRASES

    def observe_characters(self, mentions: list[Mention]) -> list[WorldChange]:
        """Упоминания одной фразы → вошёл / ушёл. Вошёл — если его не было на сцене (никогда, ушёл или
        давно молчали). Упоминание в уходе («заяц убежал») — ушёл, без звука появления.
        Обращение («ты, старый пёс») появлением не считается, но присутствие продлевает."""
        self.phrase += 1
        out, entered = [], 0
        for m in sorted(mentions, key=lambda m: m.position):
            cid = m.character.id
            if m.leaving:
                if self.present.pop(cid, None) is not None:
                    out.append(self._record(WorldChange("leave", cid, "ушёл", m.word)))
                continue
            if not self.is_present(cid):
                if m.address:
                    continue                      # к нему обращаются — но это ещё не значит, что он пришёл
                if entered >= config.MAX_CHARACTERS_PER_PHRASE:
                    continue
                out.append(self._record(WorldChange("enter", cid, "появился", m.word)))
                entered += 1
            self.present[cid] = self.phrase       # упоминание продлевает присутствие
        return out

    def on_stage(self) -> list[str]:
        return [cid for cid in self.present if self.is_present(cid)]

    def reset(self) -> None:
        self.place, self.weather, self.mood = None, [], None
        self.present.clear()
        self.phrase = 0
        self.history.clear()

    def snapshot(self) -> dict:
        return {"place": self.place, "weather": list(self.weather), "mood": self.mood, "on_stage": self.on_stage()}
