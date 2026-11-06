"""Звукооператор: насколько напряжён момент рассказа → громкость слоёв (D-010).

Два сигнала, как у живого звукооператора:
- смысл — настроение рассказа (mood.py): спокойно … динамично;
- темп речи — сколько слов в секунду говорит рассказчик за последние TEMPO_WINDOW_S.
Напряжённость 0…1 меняется плавно (INTENSITY_TAU_S) и сдвигает громкости между MIX_CALM и MIX_INTENSE.
Голос рассказчика не записывается: считаем только моменты появления новых слов.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

from . import config


@dataclass
class SoundMixer:
    clock: Callable[[], float]
    mood: str = "calm"
    intensity: float = field(default=-1.0)       # -1 — ещё не считали
    _word_times: deque = field(default_factory=deque)
    _seen_in_utt: int = 0
    _last_t: float | None = None

    def __post_init__(self):
        if self.intensity < 0:
            self.intensity = config.MOOD_INTENSITY.get(self.mood, 0.3)

    # ---------- входы ----------
    def on_words(self, n_words: int, final: bool) -> None:
        """Каждое событие распознавания: сколько слов во фразе сейчас. Новые слова — отметки времени."""
        now = self.clock()
        if n_words > self._seen_in_utt:
            self._word_times.extend([now] * (n_words - self._seen_in_utt))
            self._seen_in_utt = n_words
        if final:
            self._seen_in_utt = 0
        while self._word_times and now - self._word_times[0] > config.TEMPO_WINDOW_S:
            self._word_times.popleft()

    # ---------- оценки ----------
    def tempo(self) -> float | None:
        """Слов в секунду за окно; None — слов пока мало."""
        if len(self._word_times) < config.TEMPO_MIN_WORDS:
            return None
        span = max(self.clock() - self._word_times[0], 2.0)   # от первого слова в окне до сейчас
        return len(self._word_times) / span

    def target(self) -> float:
        m = config.MOOD_INTENSITY.get(self.mood, 0.3)
        r = self.tempo()
        if r is None:
            return m
        t = min(1.0, max(0.0, (r - config.TEMPO_SLOW) / (config.TEMPO_FAST - config.TEMPO_SLOW)))
        return (1 - config.TEMPO_WEIGHT) * m + config.TEMPO_WEIGHT * t

    def update(self) -> float:
        """Сдвинуть напряжённость к цели (плавно, по прошедшему времени). Возвращает новую."""
        now = self.clock()
        dt = 0.0 if self._last_t is None else max(0.0, now - self._last_t)
        self._last_t = now
        k = 1 - math.exp(-dt / config.INTENSITY_TAU_S)
        self.intensity += (self.target() - self.intensity) * k
        return self.intensity

    def levels(self) -> tuple[float, float, float, float]:
        """(фон, наложения, действия+персонажи, музыка) для текущей напряжённости."""
        a = self.intensity
        return tuple(c + (i - c) * a for c, i in zip(config.MIX_CALM, config.MIX_INTENSE))
