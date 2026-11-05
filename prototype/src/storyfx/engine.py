"""Связка: события текста → триггеры и сцены → команды звуковому движку."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from . import config
from .asr import TextEvent
from .scenes import SceneTracker
from .triggers import TriggerMatcher


@dataclass
class StoryEngine:
    triggers: TriggerMatcher
    scenes: SceneTracker
    audio: object                                   # PygameAudio | NullAudio
    log: Callable[[str], None] = print
    clock: Callable[[], float] = time.monotonic
    events: list[tuple[str, str]] = field(default_factory=list)   # для тестов: ("sfx", id), ("scene", id)…
    _utt: int = 0
    _last_eval: float = 0.0
    _t0: float = field(default=0.0)

    def __post_init__(self):
        self._t0 = self.clock()
        self._last_eval = self._t0

    def _say(self, msg: str) -> None:
        self.log(f"[{self.clock() - self._t0:6.1f}s] {msg}")

    def on_text(self, ev: TextEvent) -> None:
        for f in self.triggers.process(ev.text, self._utt, ev.final):
            self.audio.play_sfx(f.sfx)
            self.events.append(("sfx", f.sfx))
            self._say(f"ДЕЙСТВИЕ {f.sfx:<12} ← «{f.text}» (фраза: {f.phrase})")

        if ev.final:
            self._say(f"фраза: {ev.text}")
            self._apply(self.scenes.add_utterance(ev.text))
            self._utt += 1
            self._last_eval = self.clock()
        elif self.clock() - self._last_eval >= config.SCENE_INTERVAL_S:
            # длинная речь без пауз: периодически переоцениваем сцену с текущим частичным текстом
            self._last_eval = self.clock()
            c = self.scenes.evaluate(ev.text)
            self._apply([c] if c else [])

    def _apply(self, changes) -> None:
        overlays_changed = False
        for c in changes:
            if c.kind == "scene":
                self.audio.set_scene(self.scenes.ambience_for(c.id))
                self.events.append(("scene", c.id))
                self._say(f"СЦЕНА    {c.id:<12} ({c.reason})")
            else:
                overlays_changed = True
                self.events.append((c.kind, c.id))
                self._say(f"{'+' if c.kind == 'overlay_on' else '-'}СЛОЙ    {c.id:<12} ({c.reason})")
        if overlays_changed:
            self.audio.set_overlays([self.scenes.overlay_ambience(o) for o in self.scenes.active_overlays])
