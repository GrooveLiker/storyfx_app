"""«Тест озвучки» в каталоге: рассказчик пишет текст в поле или диктует — система слушает и озвучивает.

Текст: страница следит за полем и шлёт сюда, что рассказчик дописал (feed_text): слова недописанной
фразы — как частичный результат распознавания, закрытая фраза («.», «!», «?», Enter) — как финальный.
Диктовка: Vosk на этом компьютере (голос не сохраняется, CLAUDE.md правила 1–2); распознанные фразы
страница дописывает в то же поле (heard), повторно они не озвучиваются.
Движок — тот же, что в приложении; создаётся при первом обращении (модели грузятся в фоне).
"""
from __future__ import annotations

import re
import threading
import time
from collections import deque
from typing import Callable


def as_heard(text: str) -> str:
    """Текст рассказчика → как его отдал бы Vosk: слова без знаков препинания, строчными."""
    words = (re.sub(r"[^\w\-]", "", w).strip("-").lower() for w in text.split())
    return " ".join(w for w in words if w)


class LiveSession:
    def __init__(self, engine_factory: Callable[[Callable[[str], None]], object] | None = None,
                 mic_factory: Callable | None = None, sleep: Callable[[float], None] = time.sleep):
        self._factory = engine_factory or _default_engine
        self._mic_factory = mic_factory
        self._sleep = sleep
        self.engine = None
        self.status = "idle"             # idle → loading → ready | error
        self.error = ""
        self._lock = threading.RLock()   # движок — из запросов страницы и потока микрофона
        self._lines: deque[tuple[int, str]] = deque(maxlen=400)
        self._heard: deque[tuple[int, str]] = deque(maxlen=100)   # фразы диктовки — дописать в поле
        self._seq = 0
        self._mic_stop: threading.Event | None = None
        self._in_speech = False                 # закрытая фраза кончилась внутри «…» — следующая продолжает реплику
        self.partial = ""

    # ---------- журнал ----------
    def _next(self) -> int:
        self._seq += 1
        return self._seq

    def log(self, line: str) -> None:
        with self._lock:
            self._lines.append((self._next(), line))

    # ---------- движок ----------
    def ensure_engine(self, wait: bool = False) -> None:
        with self._lock:
            if self.status not in ("loading", "ready"):
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
            self.log("Готово. Нажмите «Начать озвучку» и пишите рассказ или диктуйте.")
        except Exception as e:                       # нет модели, нет звуковой карты и т.п.
            self.status, self.error = "error", str(e)
            self.log(f"Ошибка: {e}")

    def _feed(self, ev) -> None:
        with self._lock:
            self.partial = "" if ev.final else ev.text
            self.engine.on_text(ev)

    def _wake_music(self) -> None:
        """После «Стоп» музыка молчит; когда рассказ продолжился — снова текущее настроение (если включена)."""
        e = self.engine
        if e.music_on and getattr(e.audio, "_music", True) is None:
            e.set_music_enabled(True)

    # ---------- текст: рассказчик пишет в поле ----------
    def feed_text(self, text: str, final: bool) -> bool:
        """Что рассказчик дописал. final=False — слова недописанной фразы, True — фраза закрыта.
        Возвращает False, если слов нет (одни знаки) — ничего не отправлено."""
        if self.status != "ready":
            raise ValueError("движок ещё загружается — подождите несколько секунд")
        from storyfx.asr import TextEvent
        from storyfx.textnorm import mark_speech, speech_words
        # реплики героев («…», строки с тире) не меняют место и погоду — шаг 6 задачи 23
        words, mask, end_state = speech_words(mark_speech(text), self._in_speech)
        if not words:
            return False
        with self._lock:
            self._source("text")
            self._wake_music()
            self._feed(TextEvent(" ".join(words), final, tuple(mask)))
            if final:
                self._in_speech = end_state       # «…» может продолжиться в следующей фразе
        return True

    def _source(self, kind: str) -> None:
        """Набор текста и речь — разные ритмы: при наборе слова идут медленно, секундомер и темп врут.
        text: действия решаются по смыслу, а не по сроку (D-011 — для речи), темп не учитывается."""
        e = self.engine
        speech = kind == "speech"
        e.actions.use_deadlines = speech
        if e.mixer:
            e.mixer.use_tempo = speech

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
                self._source("speech")
                self._wake_music()
            for ev in events:
                with self._lock:
                    self._source("speech")          # могут и печатать при включённом микрофоне
                    self._feed(ev)
                if ev.final:
                    with self._lock:
                        self._heard.append((self._next(), ev.text))
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
        """Тишина и чистый лист: сцена, погода, музыка, кто на сцене, настроение."""
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
            self._in_speech = False
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

    def muted_changed(self) -> None:
        """В каталоге нажали «Не нужен» / «Вернуть» — тест озвучки сразу слушается нового списка."""
        from storyfx.muted import load_muted
        with self._lock:
            if self.engine is not None:
                self.engine.muted = load_muted()

    def state(self, since: int = 0) -> dict:
        with self._lock:
            e = self.engine
            return {
                "status": self.status, "error": self.error, "listening": self.listening,
                "partial": self.partial,
                "scene": e.world.place if e else None,
                "overlays": list(e.world.weather) if e else [],
                "on_stage": _titles(e, e.world.on_stage()) if e else [],
                "mood": e.mood if e else None,
                "intensity": round(e.mixer.intensity, 2) if e and e.mixer else None,
                "music_on": bool(e and e.music_on),
                "lines": [{"n": n, "text": t} for n, t in self._lines if n > since],
                "heard": [{"n": n, "text": t} for n, t in self._heard if n > since],
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
