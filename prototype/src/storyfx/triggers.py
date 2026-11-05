"""Быстрый слой: текст → звуки действий по ключевым фразам."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import yaml

from . import config
from .textnorm import Match, Pattern, find_matches, is_negated, parse_pattern, tokenize


@dataclass
class Trigger:
    id: str
    patterns: list[Pattern]
    cooldown: float = config.DEFAULT_COOLDOWN_S
    scary: bool = False


@dataclass
class Fired:
    sfx: str
    phrase: str      # какая фраза из triggers.yaml сработала
    text: str        # какие слова в речи её вызвали


def load_triggers(path: Path = config.DATA_DIR / "triggers.yaml") -> list[Trigger]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [
        Trigger(
            id=tid,
            patterns=[parse_pattern(p) for p in spec["phrases"]],
            cooldown=float(spec.get("cooldown", config.DEFAULT_COOLDOWN_S)),
            scary=bool(spec.get("scary", False)),
        )
        for tid, spec in raw.items()
    ]


@dataclass
class TriggerMatcher:
    triggers: list[Trigger]
    mode: str = "dnd"
    clock: Callable[[], float] = time.monotonic
    _last_fired: dict[str, float] = field(default_factory=dict)
    _seen: set[tuple[int, int]] = field(default_factory=set)   # (фраза, позиция слова) уже озвучены

    def process(self, text: str, utterance_id: int, final: bool) -> list[Fired]:
        """Вызывается на каждый частичный и финальный результат распознавания.

        Частичные результаты одной фразы приходят многократно с растущим текстом,
        поэтому запоминаем позиции, где уже сработали, и не повторяем их.
        """
        tokens = tokenize(text)
        candidates: list[tuple[Trigger, Match]] = []
        for trig in self.triggers:
            if trig.scary and self.mode == "kids":
                continue
            for pat in trig.patterns:
                for m in find_matches(pat, tokens):
                    if not is_negated(tokens, m.start, end=m.end):
                        candidates.append((trig, m))

        # Пересекающиеся совпадения: побеждает более длинная/точная фраза
        # («ударил мечом» → меч, а не просто удар кулаком).
        candidates.sort(key=lambda c: c[1].pattern.specificity, reverse=True)
        taken: set[int] = set()
        fired: list[Fired] = []
        now = self.clock()
        for trig, m in candidates:
            span = set(range(m.start, m.end + 1))
            if span & taken:
                continue
            taken |= span
            key = (utterance_id, m.start)
            if key in self._seen:
                continue
            # Совпадение у конца незаконченной фразы, которое может стать длиннее
            # («ударил» → «ударил мечом») — ждём. Последнее слово частичного результата
            # Vosk ещё может переписать («ударил меня» → «ударил мечом»), поэтому запас — 2 слова.
            if not final and m.end >= len(tokens) - 2 and self._could_extend(tokens, m):
                continue
            self._seen.add(key)
            if now - self._last_fired.get(trig.id, -1e9) < trig.cooldown:
                continue
            self._last_fired[trig.id] = now
            fired.append(Fired(trig.id, m.pattern.source, " ".join(t.word for t in tokens[m.start: m.end + 1])))

        if final:
            self._seen = {k for k in self._seen if k[0] != utterance_id}
        return fired

    def _could_extend(self, tokens, m: Match) -> bool:
        """Есть ли более длинная фраза, у которой уже совпало начало на этом месте."""
        matched_len = len(m.pattern.words)
        tail = tokens[m.start:]
        for trig in self.triggers:
            if trig.scary and self.mode == "kids":
                continue
            for pat in trig.patterns:
                if len(pat.words) <= matched_len:
                    continue
                head = Pattern(pat.words[:matched_len], pat.source)
                if any(hm.start == 0 for hm in find_matches(head, tail)):
                    return True
        return False
