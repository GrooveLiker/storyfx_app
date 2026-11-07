"""Три звена (D-011): текст (звено 1) → наблюдатели пишут в модель мира (звено 2) →
звукорежиссёр (_direct) превращает изменения мира в звук (звено 3)."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from . import config
from .asr import TextEvent
from .characters import CharacterTracker
from .mixer import SoundMixer
from .scenes import SceneTracker
from .actions import ActionMatcher
from .world import WorldChange, WorldState


@dataclass
class StoryEngine:
    actions: ActionMatcher
    scenes: SceneTracker
    audio: object                                   # PygameAudio | NullAudio
    log: Callable[[str], None] = print
    verbose: bool = True                            # печатать и решения «без звука» — помогает настраивать примеры
    clock: Callable[[], float] = time.monotonic
    events: list[tuple[str, str]] = field(default_factory=list)   # для тестов: ("sfx", id), ("scene", id)…
    moods: SceneTracker | None = None               # настроение → музыка (storyfx/mood.py); None — без музыки
    music_on: bool = False                          # музыку можно включать и выключать на ходу
    characters: CharacterTracker | None = None      # звук персонажа при появлении (storyfx/characters.py)
    mixer: SoundMixer | None = None                 # звукооператор: напряжённость → громкость слоёв (mixer.py)
    world: WorldState | None = None                 # модель мира (world.py); создаётся сама
    _said_intensity: float = -1.0
    _action_in_utt: bool = False                    # в текущей фразе уже прозвучал звук действия
    _utt: int = 0
    _last_eval: float = 0.0
    _t0: float = field(default=0.0)

    def __post_init__(self):
        self._t0 = self.clock()
        self._last_eval = self._t0
        if self.world is None:
            self.world = WorldState(clock=self.clock)
        if self.moods:
            self.world.mood = self.moods.current
        if self.music_on:
            self.set_music_enabled(True)

    def _say(self, msg: str) -> None:
        self.log(f"[{self.clock() - self._t0:6.1f}s] {msg}")

    @property
    def mood(self) -> str | None:
        if not self.moods:
            return None
        return self.world.mood or self.moods.current     # трекер могли подключить после создания движка

    def set_music_enabled(self, on: bool) -> None:
        """Вкл/выкл музыки. При включении сразу играет текущее настроение."""
        self.music_on = on and self.moods is not None
        self.audio.set_music(self.moods.ambience_for(self.mood) if self.music_on else None)
        self._say(f"МУЗЫКА   {'вкл: ' + str(self.mood) if self.music_on else 'выкл'}")

    def on_text(self, ev: TextEvent) -> None:
        if self.mixer:
            self.mixer.on_words(len(ev.text.split()), ev.final)
        self._on_text(ev)
        if self.mixer:
            self._mix()

    def _mix(self) -> None:
        if self.mood:
            self.mixer.mood = self.mood
        a = self.mixer.update()
        self.audio.set_mix(self.mixer.levels())
        if abs(a - self._said_intensity) >= 0.1:       # в журнал — только заметные сдвиги
            self._said_intensity = a
            tempo = self.mixer.tempo()
            self._say(f"ЗВУКООПЕРАТОР напряжение {a:.1f} (настроение {self.mixer.mood}"
                      f"{f', темп {tempo:.1f} сл/с' if tempo else ''})")

    # ---------- звено 2: наблюдатели → мир ----------
    def _on_text(self, ev: TextEvent) -> None:
        w = self.world
        for d in self.actions.process(ev.text, self._utt, ev.final):
            if d.sfx:
                self._direct([w.action(d.sfx, f"«{d.context}» ({d.group}, {d.confidence:.2f})")])
            elif self.verbose:
                self._say(f"  тише   {d.group:<12} ← «{d.context}» ({d.note}, {d.confidence:.2f})")

        if ev.final:
            self._say(f"фраза: {ev.text}")
            if self.characters:
                self._direct(w.observe_characters(self.characters.observe(ev.text)))
            self._action_in_utt = False
            self._observe_scene(self.scenes.add_utterance(ev.text))
            if self.moods:
                self._observe_mood(self.moods.add_utterance(ev.text))
            self._utt += 1
            self._last_eval = self.clock()
        elif self.clock() - self._last_eval >= config.SCENE_INTERVAL_S:
            # длинная речь без пауз: периодически переоцениваем сцену с текущим частичным текстом
            self._last_eval = self.clock()
            c = self.scenes.evaluate(ev.text)
            self._observe_scene([c] if c else [])
            if self.moods:
                m = self.moods.evaluate(ev.text)
                self._observe_mood([m] if m else [])

    def _observe_scene(self, changes) -> None:
        out, weather = [], []
        for c in changes:
            if c.kind == "scene":
                out += self.world.set_place(c.id, c.reason)
            else:
                weather.append((c.id, c.kind == "overlay_on", c.reason))
        if weather:
            out += self.world.set_weather(self.scenes.active_overlays, weather)
        self._direct(out)

    def _observe_mood(self, changes) -> None:
        for c in changes:
            if c.kind == "scene":       # у трекера настроений нет наложений
                self._direct(self.world.set_mood(c.id, c.reason))

    # ---------- звено 3: звукорежиссёр — изменения мира → звук ----------
    def _direct(self, changes: list[WorldChange]) -> None:
        weather_changed = False
        for c in changes:
            if c.kind == "action":
                self.audio.play_sfx(c.id)
                self._action_in_utt = True
                self.events.append(("sfx", c.id))
                self._say(f"ДЕЙСТВИЕ {c.id:<12} ← {c.reason}")
            elif c.kind == "enter":
                ch = next(x for x in self.characters.characters if x.id == c.id)
                if self._action_in_utt:
                    # «волк завыл»: звук действия уже есть — второй звук того же момента будет кашей
                    self._say(f"  тише   персонаж {c.id:<9} ← «{c.word}» (в фразе уже был звук действия)")
                    continue
                self.audio.play_sfx(ch.sound)
                self.events.append(("char", c.id))
                self._say(f"ПЕРСОНАЖ {c.id:<12} ← «{c.word}» ({ch.sound})")
            elif c.kind == "leave":
                self.events.append(("leave", c.id))
                self._say(f"УШЁЛ     {c.id:<12} ← «{c.word}»")
            elif c.kind == "place":
                self.audio.set_scene(self.scenes.ambience_for(c.id))
                self.events.append(("scene", c.id))
                self._say(f"СЦЕНА    {c.id:<12} ({c.reason})")
            elif c.kind in ("weather_on", "weather_off"):
                weather_changed = True
                kind = "overlay_on" if c.kind == "weather_on" else "overlay_off"
                self.events.append((kind, c.id))
                self._say(f"{'+' if kind == 'overlay_on' else '-'}СЛОЙ    {c.id:<12} ({c.reason})")
            elif c.kind == "mood":
                self.events.append(("mood", c.id))
                self._say(f"НАСТРОЕНИЕ {c.id:<10} ({c.reason}){'' if self.music_on else ' — музыка выкл'}")
                if self.music_on:
                    self.audio.set_music(self.moods.ambience_for(c.id))
        if weather_changed:
            self.audio.set_overlays([self.scenes.overlay_ambience(o) for o in self.world.weather])
