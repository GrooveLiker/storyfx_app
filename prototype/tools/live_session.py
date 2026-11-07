"""«Тест озвучки» в каталоге: настоящий движок приложения, текст или диктовка → звук из колонок.

Движок создаётся при первом обращении (модели грузятся несколько секунд — в фоне).
Текст подаётся по словам в темпе речи (звукооператор слышит темп). Диктовка — Vosk на этом
компьютере; голос не сохраняется (CLAUDE.md, правила 1–2).
"""
from __future__ import annotations

import queue
import re
import threading
import time
from collections import deque
from typing import Callable

TEMPO = {"slow": 0.6, "normal": 0.4, "fast": 0.22}     # секунд на слово: ≈1,7 / 2,5 / 4,5 сл/с


def split_phrases(text: str) -> list[str]:
    """Фразы — как паузы рассказчика: по . ! ? … и переносам строк."""
    return [p.strip() for p in re.split(r"[.!?…\n]+", text) if p.strip()]


class LiveSession:
    def __init__(self, engine_factory: Callable[[Callable[[str], None]], object] | None = None,
                 mic_factory: Callable | None = None, sleep: Callable[[float], None] = time.sleep):
        self._factory = engine_factory or _default_engine
        self._mic_factory = mic_factory
        self._sleep = sleep
        self.engine = None
        self.status = "idle"             # idle → loading → ready | error
        self.error = ""
        self._lock = threading.RLock()   # движок — из потока текста и потока микрофона
        self._lines: deque[tuple[int, str]] = deque(maxlen=400)
        self._seq = 0
        self._texts: queue.Queue[tuple[str, float]] = queue.Queue()
        self._cancel = threading.Event()
        self._busy = False
        self._mic_stop: threading.Event | None = None
        self.partial = ""
        threading.Thread(target=self._text_worker, daemon=True).start()

    # ---------- журнал ----------
    def log(self, line: str) -> None:
        with self._lock:
            self._seq += 1
            self._lines.append((self._seq, line))

    # ---------- движок ----------
    def ensure_engine(self, wait: bool = False) -> None:
        with self._lock:
            if self.status in ("loading", "ready"):
                pass
            else:
                self.status, self.error = "loading", ""
                threading.Thread(target=self._load, daemon=True).start()
        if wait:
            while self.status == "loading":
                self._sleep(0.05)

    def _load(self) -> None:
        try:
            self.log("Загрузка движка и моделей…")
            eng = self._factory(self.log)
            with self._lock:
                self.engine, self.status = eng, "ready"
            self.log("Готово. Пишите текст или диктуйте.")
        except Exception as e:                       # нет модели, нет звуковой карты и т.п.
            self.status, self.error = "error", str(e)
            self.log(f"Ошибка: {e}")

    def _feed(self, ev) -> None:
        with self._lock:
            self.partial = "" if ev.final else ev.text
            self.engine.on_text(ev)

    def _wake_music(self) -> None:
        """После «Стоп» музыка молчит; при новом рассказе — снова текущее настроение (если включена)."""
        e = self.engine
        if e.music_on and getattr(e.audio, "_music", True) is None:
            e.set_music_enabled(True)

    # ---------- текст ----------
    def say(self, text: str, tempo: str = "normal") -> int:
        phrases = split_phrases(text)
        if not phrases:
            return 0
        self.ensure_engine()
        self._cancel.clear()
        for p in phrases:
            self._texts.put((p, TEMPO.get(tempo, TEMPO["normal"])))
        return len(phrases)

    def _text_worker(self) -> None:
        from storyfx.asr import TextEvent
        while True:
            phrase, delay = self._texts.get()
            self._busy = True
            try:
                while self.status == "loading":
                    self._sleep(0.1)
                if self.status != "ready" or self._cancel.is_set():
                    continue
                with self._lock:
                    self._wake_music()
                words = phrase.split()
                for i in range(1, len(words) + 1):
                    if self._cancel.is_set():
                        break
                    self._feed(TextEvent(" ".join(words[:i]), False))
                    self._sleep(delay)
                else:
                    self._feed(TextEvent(" ".join(words), True))
                    self._sleep(delay * 2)               # пауза между фразами — как у рассказчика
            finally:
                self._busy = self._texts.qsize() > 0

    # ---------- микрофон ----------
    @property
    def listening(self) -> bool:
        return self._mic_stop is not None

    def mic_start(self, device: int | None = None) -> None:
        if self.listening:
            return
        self.ensure_engine()
        stop = threading.Event()
        self._mic_stop = stop
        threading.Thread(target=self._mic_worker, args=(device, stop), daemon=True).start()

    def _mic_worker(self, device, stop: threading.Event) -> None:
        try:
            while self.status == "loading":
                self._sleep(0.1)
            if self.status != "ready":
                return
            from storyfx.asr import mic_events
            events = (self._mic_factory or mic_events)(device=device, stop=stop)
            self.log("🎤 Слушаю микрофон (голос не сохраняется). Лучше в наушниках.")
            with self._lock:
                self._wake_music()
            for ev in events:
                self._feed(ev)
        except Exception as e:
            self.log(f"Ошибка микрофона: {e}")
        finally:
            if self._mic_stop is stop:
                self._mic_stop = None
            self.partial = ""
            self.log("🎤 Микрофон выключен.")

    def mic_stop(self) -> None:
        if self._mic_stop:
            self._mic_stop.set()

    # ---------- управление ----------
    def stop(self) -> None:
        """Тишина и чистый лист: очередь текста, сцена, погода, музыка, персонажи, настроение."""
        self._cancel.set()
        while not self._texts.empty():
            try:
                self._texts.get_nowait()
            except queue.Empty:
                break
        self.mic_stop()
        with self._lock:
            e = self.engine
            if e is None:
                return
            e.audio.set_scene(None)
            e.audio.set_overlays([])
            e.audio.set_music(None)
            e.scenes.current, e.scenes.active_overlays, e.scenes._words = None, [], []
            e.scenes._candidate, e.scenes._candidate_hits = None, 0
            e.world.reset()                          # место, погода, кто на сцене
            if e.moods:
                e.moods._words, e.moods._candidate, e.moods._candidate_hits = [], None, 0
                e.moods.current = e.world.mood = _default_mood()
            e.actions._last_fired.clear()
            if e.mixer:
                from storyfx.mixer import SoundMixer
                e.mixer = SoundMixer(clock=e.mixer.clock, mood=e.mood or "calm")
            self.partial = ""
        self.log("■ Стоп: тишина, рассказ с чистого листа.")

    def set_music(self, on: bool) -> None:
        self.ensure_engine(wait=True)
        with self._lock:
            if self.engine:
                self.engine.set_music_enabled(on)

    def sound_changed(self) -> None:
        """В каталоге выбрали другой вариант звука — забыть загруженные файлы, взять новые."""
        with self._lock:
            cache = getattr(getattr(self.engine, "audio", None), "_cache", None)
            if cache is not None:
                cache.clear()

    def state(self, since: int = 0) -> dict:
        with self._lock:
            e = self.engine
            return {
                "status": self.status, "error": self.error,
                "busy": self._busy or not self._texts.empty(), "listening": self.listening,
                "partial": self.partial,
                "scene": e.world.place if e else None,
                "overlays": list(e.world.weather) if e else [],
                "on_stage": _titles(e, e.world.on_stage()) if e else [],
                "mood": e.mood if e else None,
                "intensity": round(e.mixer.intensity, 2) if e and e.mixer else None,
                "music_on": bool(e and e.music_on),
                "lines": [{"n": n, "text": t} for n, t in self._lines if n > since],
                "last": self._seq,
            }


def _titles(engine, ids: list[str]) -> list[str]:
    """Кто на сцене — именами для людей («Баба-яга»), а не id."""
    by_id = {c.id: c.title for c in engine.characters.characters} if engine.characters else {}
    return [by_id.get(i, i) for i in ids]


def _default_mood() -> str:
    from storyfx.mood import load_moods
    return load_moods()[1]


def _default_engine(log: Callable[[str], None]):
    from storyfx.audio import PygameAudio
    from storyfx.cli import build_engine
    return build_engine(PygameAudio(), use_embedder=True, log=log, music=True)
