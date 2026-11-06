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

    def set_music(self, music: str | None) -> None:
        self.log.append(("music", music))

    def set_mix(self, levels: tuple[float, float, float, float]) -> None:
        self.mix = levels           # не в log: меняется почти на каждом слове

    def close(self) -> None:
        pass


class PygameAudio:
    def __init__(self, sounds_dir: Path = config.SOUNDS_DIR, crossfade_ms: int = config.CROSSFADE_MS):
        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        import pygame
        self.pg = pygame
        pygame.mixer.pre_init(44100, -16, 2, 512)   # малый буфер = малая задержка
        pygame.mixer.init()
        pygame.mixer.set_num_channels(32)
        pygame.mixer.set_reserved(2)       # каналы 0 и 1 — только музыка: find_channel их не отдаст звукам
        self.dir = sounds_dir
        self.xfade = crossfade_ms
        self.vol_scene, self.vol_overlay, self.vol_sfx, self.vol_music = config.MIX_CALM   # дальше — set_mix
        self._cache: dict[Path, object] = {}
        self._scene: tuple[str, object] | None = None          # (ambience, Channel)
        self._overlays: dict[str, object] = {}                 # ambience → Channel
        self._music: tuple[str, int] | None = None             # (имя, номер канала 0/1)
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

    def set_mix(self, levels: tuple[float, float, float, float]) -> None:
        """Звукооператор: новые громкости слоёв — сразу для играющих петель и для следующих звуков.
        Плавность обеспечивает mixer.py (маленькие шаги на каждом слове)."""
        self.vol_scene, self.vol_overlay, self.vol_sfx, self.vol_music = levels
        if self._scene:
            self._scene[1].set_volume(self.vol_scene)
        for ch in self._overlays.values():
            ch.set_volume(self.vol_overlay)
        if self._music:
            self.pg.mixer.Channel(self._music[1]).set_volume(self.vol_music)

    def set_music(self, music: str | None) -> None:
        """Сменить петлю музыки (None — выключить). Старая затухает, новая нарастает на втором канале."""
        if (self._music[0] if self._music else None) == music:
            return
        nxt = 0
        if self._music:
            self.pg.mixer.Channel(self._music[1]).fadeout(config.MUSIC_CROSSFADE_MS)
            nxt = 1 - self._music[1]
            self._music = None
        if music:
            snd = self._sound("music", music)
            if snd is not None:
                ch = self.pg.mixer.Channel(nxt)
                ch.set_volume(self.vol_music)
                ch.play(snd, loops=-1, fade_ms=config.MUSIC_CROSSFADE_MS)
                self._music = (music, nxt)

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
