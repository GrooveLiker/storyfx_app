"""Реплики героев в речи без кавычек (голос): какие слова фразы — голос героя, а не рассказчика.

У текста реплики видны по кавычкам и тире (textnorm.mark_speech). У Vosk знаков нет, поэтому —
по словам (data/speech.yaml): обращение-повтор («печка, печка»), повелительный глагол («не ходи»,
«спрячь»), первое и второе лицо («хочу», «тебя», «мой»). Отмечается признак и несколько слов после
него, до глагола повествования — фраза Vosk длинная, в ней бывают и реплика, и рассказ.
Используется только для места и погоды (scenes.py) — задача 23, голос.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from . import config


@dataclass
class SpeechCues:
    window: int
    pronouns: frozenset[str]
    first_person: frozenset[str]
    imperatives: frozenset[str]
    narration_endings: tuple[str, ...]

    def _is_cue(self, words: list[str], i: int) -> bool:
        w = words[i]
        if w in self.pronouns or w in self.first_person or w in self.imperatives:
            return True
        # обращение-повтор: «печка печка», «яблоня яблоня» (не «и и», не короткие слова)
        return len(w) >= 3 and i + 1 < len(words) and words[i + 1] == w

    def _is_narration(self, w: str) -> bool:
        return len(w) >= 6 and w.endswith(self.narration_endings)

    def guess(self, words: list[str]) -> tuple[bool, ...]:
        """Слова (как в tokenize) → признак «в реплике» для каждого."""
        mask = [False] * len(words)
        for i in range(len(words)):
            if not self._is_cue(words, i):
                continue
            mask[i] = True
            if i + 1 < len(words) and words[i + 1] == words[i]:
                mask[i + 1] = True                       # второе слово обращения
            for j in range(i + 1, min(len(words), i + 1 + self.window)):
                if self._is_narration(words[j]):
                    break
                mask[j] = True
        return tuple(mask)


def load_speech_cues(path: Path = config.DATA_DIR / "speech.yaml") -> SpeechCues:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    norm = lambda xs: frozenset(str(x).lower().replace("ё", "е") for x in xs)   # noqa: E731
    imperatives = norm(x for x in raw.get("imperatives", []) if " " not in str(x))
    return SpeechCues(
        window=int(raw.get("window", 3)),
        pronouns=norm(raw.get("pronouns", [])),
        first_person=norm(raw.get("first_person", [])),
        imperatives=imperatives,
        narration_endings=tuple(raw.get("narration_endings", [])),
    )
