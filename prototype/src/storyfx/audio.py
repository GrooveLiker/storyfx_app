"""Звуковой движок: слой сцены, слои наложений (с кроссфейдом) и разовые звуки действий."""
from __future__ import annotations

import os
from pathlib import Path

from . import config


class NullAudio:
    """Ничего не играет, только запоминает команды. Для тестов и --no-audio."""

    def __init__(self):
        self.log: list[tuple[str, str | None]] = []

    def set_scene(self, ambience: str | None) -> None:
        self.log.append(("scene", ambience))

    def set_overlays(self, ambiences: list[str]) -> None:
        self.log.append(("overlays", ",".join(ambiences)))

    def play_sfx(self, sfx: str) -> None:
        self.log.append(("sfx", sfx))

    def close(self) -> None:
        pass


class PygameAudio:
    def __init__(self, mode: str = "dnd", sounds_dir: Path = config.SOUNDS_DIR,
                 crossfade_ms: int = config.CROSSFADE_MS):
        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        import pygame
        self.pg = pygame
        pygame.mixer.pre_init(44100, -16, 2, 512)   # малый буфер = малая задержка
        pygame.mixer.init()
        pygame.mixer.set_num_channels(32)
        self.dir = sounds_dir
        self.xfade = crossfade_ms
        self.vol_scene, self.vol_overlay, self.vol_sfx = config.VOLUMES[mode]
        self._cache: dict[Path, object] = {}
        self._scene: tuple[str, object] | None = None          # (ambience, Channel)
        self._overlays: dict[str, object] = {}                 # ambience → Channel
        missing = [p for p in [self.dir / "ambience", self.dir / "sfx"] if not p.exists()]
        if missing:
            raise FileNotFoundError(f"нет папок со звуками: {missing}. Запустите tools/gen_sounds.py")

    def _sound(self, kind: str, name: str):
        path = self.dir / kind / f"{name}.wav"
        if path not in self._cache:
            if not path.exists():
                print(f"  [audio] нет файла {path}")
                return None
            self._cache[path] = self.pg.mixer.Sound(str(path))
        return self._cache[path]

    def _start_loop(self, name: str, volume: float):
        snd = self._sound("ambience", name)
        if snd is None:
            return None
        ch = self.pg.mixer.find_channel(True)
        ch.set_volume(volume)
        ch.play(snd, loops=-1, fade_ms=self.xfade)
        return ch

    def set_scene(self, ambience: str | None) -> None:
        if self._scene and self._scene[0] == ambience:
            return
        if self._scene:
            self._scene[1].fadeout(self.xfade)
            self._scene = None
        if ambience:
            ch = self._start_loop(ambience, self.vol_scene)
            if ch:
                self._scene = (ambience, ch)

    def set_overlays(self, ambiences: list[str]) -> None:
        for name in list(self._overlays):
            if name not in ambiences:
                self._overlays.pop(name).fadeout(self.xfade)
        for name in ambiences:
            if name not in self._overlays:
                ch = self._start_loop(name, self.vol_overlay)
                if ch:
                    self._overlays[name] = ch

    def play_sfx(self, sfx: str) -> None:
        snd = self._sound("sfx", sfx)
        if snd is None:
            return
        ch = self.pg.mixer.find_channel(True)
        ch.set_volume(self.vol_sfx)
        ch.play(snd)

    def close(self) -> None:
        self.pg.mixer.fadeout(800)
        self.pg.time.wait(850)
        self.pg.mixer.quit()
