"""Источники текста: микрофон или WAV через Vosk, либо ввод текста с клавиатуры."""
from __future__ import annotations

import json
import queue
import sys
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from . import config


@dataclass
class TextEvent:
    text: str
    final: bool
    speech: tuple[bool, ...] | None = None   # для текста: какие слова (как в tokenize) — в реплике героя


class VoskStream:
    """Превращает поток PCM 16 кГц моно в частичные/финальные результаты."""

    def __init__(self, model_dir: Path = config.VOSK_MODEL_DIR, sample_rate: int = config.SAMPLE_RATE,
                 word_times: bool = False):
        import vosk
        vosk.SetLogLevel(-1)
        if not model_dir.exists():
            raise FileNotFoundError(f"нет модели Vosk: {model_dir}. Запустите init.ps1")
        self.rec = vosk.KaldiRecognizer(vosk.Model(str(model_dir)), sample_rate)
        if word_times:
            self.rec.SetWords(True)     # для теста задержки: когда каждое слово закончилось
        self.last_words: list[dict] = []   # [{"word", "start", "end"}] последней финальной фразы
        self._last_partial = ""
        self._quiet_blocks = 0

    def feed(self, pcm: bytes) -> Iterator[TextEvent]:
        if self.rec.AcceptWaveform(pcm):
            res = json.loads(self.rec.Result())
            text = res.get("text", "")
            self.last_words = res.get("result", [])
            self._last_partial = ""
            if text:
                yield TextEvent(text, True)
        else:
            partial = json.loads(self.rec.PartialResult()).get("partial", "")
            self._quiet_blocks += 1
            # Новый текст — сразу. Тот же текст — повторяем раз в PARTIAL_PULSE_BLOCKS («пульс»):
            # рассказчик замолчал после «…ухнула сова», а движку надо заметить, что срок решения вышел (D-011).
            if partial and (partial != self._last_partial or self._quiet_blocks >= config.PARTIAL_PULSE_BLOCKS):
                self._last_partial = partial
                self._quiet_blocks = 0
                yield TextEvent(partial, False)

    def flush(self) -> Iterator[TextEvent]:
        res = json.loads(self.rec.FinalResult())
        text = res.get("text", "")
        self.last_words = res.get("result", [])
        if text:
            yield TextEvent(text, True)


def mic_events(device: int | None = None, stop=None) -> Iterator[TextEvent]:
    """Микрофон → Vosk. Звук только в памяти, на диск не пишется (CLAUDE.md, правило 2).
    stop — threading.Event: установили — дочитываем фразу и выходим (кнопка «Стоп» в каталоге)."""
    import sounddevice as sd
    q: queue.Queue[bytes] = queue.Queue()

    def cb(indata, frames, t, status):
        q.put(bytes(indata))

    stream = VoskStream()
    block = int(config.SAMPLE_RATE * config.BLOCK_SECONDS)
    with sd.RawInputStream(samplerate=config.SAMPLE_RATE, blocksize=block, dtype="int16",
                           channels=1, device=device, callback=cb):
        while stop is None or not stop.is_set():
            try:
                pcm = q.get(timeout=0.2)
            except queue.Empty:
                continue
            yield from stream.feed(pcm)
    yield from stream.flush()


def wav_events(path: Path, realtime: bool = True) -> Iterator[TextEvent]:
    with wave.open(str(path), "rb") as w:
        if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (config.SAMPLE_RATE, 1, 2):
            raise ValueError(f"{path}: нужен WAV 16 кГц, моно, 16 бит")
        stream = VoskStream()
        block = int(config.SAMPLE_RATE * config.BLOCK_SECONDS)
        while True:
            data = w.readframes(block)
            if not data:
                break
            yield from stream.feed(data)
            if realtime:
                time.sleep(config.BLOCK_SECONDS)
        yield from stream.flush()


def text_events(lines: Iterator[str], word_delay: float = 0.15) -> Iterator[TextEvent]:
    """Имитация распознавания: каждая строка выдаётся по словам как частичные результаты, затем финал."""
    for line in lines:
        words = line.strip().split()
        if not words:
            continue
        for i in range(1, len(words) + 1):
            yield TextEvent(" ".join(words[:i]), False)
            if word_delay:
                time.sleep(word_delay)
        yield TextEvent(" ".join(words), True)


def stdin_lines() -> Iterator[str]:
    print("Вводите текст рассказа построчно (Ctrl+C — выход):")
    for line in sys.stdin:
        yield line
