"""Подготовка внешних звуков: декодирование (ffmpeg), обрезка тишины, громкость, бесшовная петля."""
from __future__ import annotations

import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np

SR = 44100

# целевая громкость: (RMS, максимум пика). Фон тише действий.
SFX_LEVEL = (0.10, 0.95)
AMB_LEVEL = (0.06, 0.60)


def decode(path: Path, sr: int = SR) -> np.ndarray:
    """Любой аудиофайл → моно float32 [-1, 1] через ffmpeg."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("нужен ffmpeg в PATH (https://www.gyan.dev/ffmpeg/builds/)")
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"],
        check=True, capture_output=True,
    ).stdout
    return np.frombuffer(out, dtype="<i2").astype(np.float32) / 32768


def write_wav(path: Path, x: np.ndarray, sr: int = SR) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def _level(x: np.ndarray, rms_target: float, peak_max: float) -> np.ndarray:
    rms = float(np.sqrt(np.mean(x ** 2))) + 1e-9
    peak = float(np.max(np.abs(x))) + 1e-9
    return x * min(rms_target / rms, peak_max / peak)


def _fade(x: np.ndarray, fade_in: float, fade_out: float, sr: int) -> np.ndarray:
    x = x.copy()
    a, b = min(len(x), int(fade_in * sr)), min(len(x), int(fade_out * sr))
    if a:
        x[:a] *= np.linspace(0, 1, a)
    if b:
        x[-b:] *= np.linspace(1, 0, b)
    return x


def trim_silence(x: np.ndarray, sr: int = SR, below_peak_db: float = 40.0, pad: float = 0.01) -> np.ndarray:
    """Отрезает тишину в начале и конце (порог — на N дБ ниже пика, по окнам 10 мс)."""
    win = max(1, int(0.01 * sr))
    n = len(x) // win
    if n == 0:
        return x
    env = np.abs(x[: n * win]).reshape(n, win).max(axis=1)
    loud = np.nonzero(env > env.max() * 10 ** (-below_peak_db / 20))[0]
    if len(loud) == 0:
        return x
    start = max(0, loud[0] * win - int(pad * sr))
    end = min(len(x), (loud[-1] + 1) * win + int(pad * sr))
    return x[start:end]


def process_sfx(x: np.ndarray, cut: float, sr: int = SR) -> np.ndarray:
    """Короткий звук: без тишины по краям, не длиннее cut секунд, ровная громкость."""
    y = trim_silence(x, sr)
    if len(y) > int(cut * sr):
        y = _fade(y[: int(cut * sr)], 0, 0.15, sr)       # обрезали посередине — плавно гасим
    y = _fade(y, 0.003, 0.02, sr)
    return _level(y, *SFX_LEVEL)


def loopify(x: np.ndarray, xfade: float, sr: int = SR) -> np.ndarray:
    """Склеивает хвост с началом: при повторе по кругу нет щелчка и скачка."""
    n = int(xfade * sr)
    if len(x) <= 2 * n:
        raise ValueError("слишком короткий фрагмент для петли")
    fade = np.linspace(0, 1, n)
    joined = x[-n:] * np.sqrt(1 - fade) + x[:n] * np.sqrt(fade)   # равная мощность при кроссфейде
    return np.concatenate([joined, x[n:-n]])


def process_ambience(x: np.ndarray, cut: float, sr: int = SR, xfade: float = 2.0) -> np.ndarray:
    """Фон: берём cut секунд из середины записи (без начала/конца с шорохами), делаем петлю."""
    need = int((cut + xfade) * sr)
    if len(x) < int(10 * sr):
        raise ValueError(f"запись короче 10 с ({len(x) / sr:.1f} с)")
    if len(x) > need:
        start = (len(x) - need) // 2
        x = x[start: start + need]
    return _level(loopify(x, xfade, sr), *AMB_LEVEL)
