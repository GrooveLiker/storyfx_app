"""Синтез звуков-заглушек (фон и действия) — без внешних файлов и лицензий.

Запуск:  python tools/gen_sounds.py [--force]
Существующие файлы не перезаписываются без --force, чтобы не затереть настоящие звуки.
"""
from __future__ import annotations

import argparse
import sys
import wave
from pathlib import Path

import numpy as np
from scipy import signal

SR = 44100
ROOT = Path(__file__).resolve().parents[1]
AMB_DIR = ROOT / "sounds" / "ambience"
SFX_DIR = ROOT / "sounds" / "sfx"
rng = np.random.default_rng(42)


# ---------- примитивы ----------
def t_axis(dur: float) -> np.ndarray:
    return np.arange(int(dur * SR)) / SR


def noise(dur: float) -> np.ndarray:
    return rng.standard_normal(int(dur * SR))


def filt(x: np.ndarray, kind: str, freq, order: int = 4) -> np.ndarray:
    sos = signal.butter(order, freq, btype=kind, fs=SR, output="sos")
    return signal.sosfilt(sos, x)


def smooth_rand(dur: float, rate_hz: float, lo: float = 0.0, hi: float = 1.0) -> np.ndarray:
    """Медленно меняющаяся случайная огибающая."""
    n = int(dur * SR)
    pts = max(int(dur * rate_hz) + 3, 4)
    ctrl = rng.uniform(lo, hi, pts)
    return np.interp(np.linspace(0, pts - 1, n), np.arange(pts), ctrl)


def exp_env(dur: float, decay: float, attack: float = 0.002) -> np.ndarray:
    t = t_axis(dur)
    env = np.exp(-t / decay)
    a = int(attack * SR)
    if a > 0:
        env[:a] *= np.linspace(0, 1, a)
    return env


def place(dst: np.ndarray, src: np.ndarray, at_s: float, gain: float = 1.0) -> None:
    i = int(at_s * SR)
    if i >= len(dst):
        return
    j = min(len(dst), i + len(src))
    dst[i:j] += src[: j - i] * gain


def reverb(x: np.ndarray, length: float = 1.5, mix: float = 0.4) -> np.ndarray:
    ir = noise(length) * np.exp(-t_axis(length) / (length / 5))
    ir = filt(ir, "lowpass", 4000, 2)
    wet = signal.fftconvolve(x, ir)[: len(x)]
    wet /= np.max(np.abs(wet)) + 1e-9
    dry = x / (np.max(np.abs(x)) + 1e-9)
    return dry * (1 - mix) + wet * mix


def loopify(x: np.ndarray, xfade: float = 1.0) -> np.ndarray:
    """Склеивает хвост с началом, чтобы зацикливание было без щелчка."""
    n = int(xfade * SR)
    head, body, tail = x[:n], x[n:-n], x[-n:]
    fade = np.linspace(0, 1, n)
    joined = tail * (1 - fade) + head * fade
    return np.concatenate([joined, body])


def norm(x: np.ndarray, peak: float) -> np.ndarray:
    return x / (np.max(np.abs(x)) + 1e-9) * peak


def tone(freq, dur: float, decay: float | None = None) -> np.ndarray:
    t = t_axis(dur)
    if callable(freq):
        f = freq(t)
        ph = 2 * np.pi * np.cumsum(f) / SR
    else:
        ph = 2 * np.pi * freq * t
    y = np.sin(ph)
    if decay:
        y *= exp_env(dur, decay)
    return y


def chirp(f0: float, f1: float, dur: float) -> np.ndarray:
    t = t_axis(dur)
    f = f0 + (f1 - f0) * t / dur
    y = np.sin(2 * np.pi * np.cumsum(f) / SR)
    return y * np.hanning(len(y))


# ---------- элементы ----------
def bird_calls(dur: float, density: float) -> np.ndarray:
    out = np.zeros(int(dur * SR))
    t = 0.3
    while t < dur - 1:
        base = rng.uniform(2500, 4500)
        for k in range(rng.integers(2, 6)):
            c = chirp(base * rng.uniform(0.9, 1.1), base * rng.uniform(1.1, 1.5), rng.uniform(0.04, 0.12))
            place(out, c, t + k * 0.11, rng.uniform(0.3, 1.0))
        t += rng.exponential(1 / density)
    return out


def drips(dur: float, density: float) -> np.ndarray:
    out = np.zeros(int(dur * SR))
    t = 0.2
    while t < dur - 0.5:
        f = rng.uniform(900, 2200)
        d = tone(lambda tt, f=f: f * (1 + 0.8 * np.exp(-tt * 40)), 0.15, 0.03)
        place(out, d, t, rng.uniform(0.4, 1.0))
        t += rng.exponential(1 / density)
    return out


def murmur(dur: float, voices: int) -> np.ndarray:
    out = np.zeros(int(dur * SR))
    for _ in range(voices):
        center = rng.uniform(300, 900)
        v = filt(noise(dur), "bandpass", [center * 0.6, center * 1.6], 2)
        syl = smooth_rand(dur, rng.uniform(4, 7), 0, 1) ** 3
        gate = smooth_rand(dur, 0.3, 0, 1) > 0.35
        out += v * syl * gate
    return out


def crackle(dur: float, density: float) -> np.ndarray:
    out = np.zeros(int(dur * SR))
    n = int(dur * density)
    for at in rng.uniform(0, dur - 0.05, n):
        c = filt(noise(0.01), "highpass", 1500, 2) * exp_env(0.01, 0.002)
        place(out, c, at, rng.uniform(0.2, 1.0))
    return out


def metal_ping(base: float, dur: float = 0.8, decay: float = 0.25) -> np.ndarray:
    ratios = [1.0, 2.21, 3.25, 4.5, 5.9]
    y = sum(tone(base * r, dur, decay / (1 + i * 0.4)) / (1 + i * 0.6) for i, r in enumerate(ratios))
    return y


def thump(freq: float = 80, dur: float = 0.3) -> np.ndarray:
    body = tone(lambda t: freq * (1 + 1.5 * np.exp(-t * 30)), dur, dur / 4)
    click = filt(noise(dur), "lowpass", 900) * exp_env(dur, 0.02)
    return body + 0.5 * click


def whoosh(dur: float, f0: float, f1: float, f2: float) -> np.ndarray:
    n = int(dur * SR)
    x = noise(dur)
    centers = np.interp(np.linspace(0, 1, n), [0, 0.5, 1], [f0, f1, f2])
    out = np.zeros(n)
    block = 512
    for i in range(0, n, block):
        c = centers[i]
        seg = filt(x[max(0, i - 2048): i + block], "bandpass", [c * 0.7, min(c * 1.4, SR / 2 - 100)], 2)
        out[i: i + block] = seg[-len(out[i: i + block]):]
    return out * np.hanning(n)


def rumble(dur: float, decay: float) -> np.ndarray:
    return filt(noise(dur), "lowpass", 180) * exp_env(dur, decay, attack=0.05) * smooth_rand(dur, 6, 0.4, 1)


# ---------- фоны (≈14 с, зациклены) ----------
AD = 14.0


def amb_wind():
    base = filt(noise(AD + 1), "lowpass", 500) * smooth_rand(AD + 1, 0.3, 0.3, 1)
    whistle = filt(noise(AD + 1), "bandpass", [700, 1100], 2) * smooth_rand(AD + 1, 0.2, 0, 0.4)
    return base + whistle


def amb_rain():
    hiss = filt(noise(AD + 1), "bandpass", [800, 9000], 2)
    drops = crackle(AD + 1, 300) * 3
    return hiss * 0.6 + filt(drops, "lowpass", 6000)


def amb_storm():
    x = amb_rain() * 1.2 + filt(noise(AD + 1), "lowpass", 400) * smooth_rand(AD + 1, 0.3, 0.2, 0.8)
    place(x, rumble(4, 1.2) * 4, 3.0)
    place(x, rumble(4, 1.5) * 3, 9.0)
    return x


def amb_forest():
    return filt(noise(AD + 1), "lowpass", 400) * smooth_rand(AD + 1, 0.3, 0.1, 0.35) * 2 + bird_calls(AD + 1, 1.2) * 0.25


def amb_meadow():
    return filt(noise(AD + 1), "lowpass", 300) * smooth_rand(AD + 1, 0.3, 0.1, 0.3) * 2 + bird_calls(AD + 1, 0.5) * 0.2


def amb_night():
    out = filt(noise(AD + 1), "lowpass", 250) * 0.4
    t = t_axis(AD + 1)
    for f, rate, period in [(4600, 32, 0.9), (5100, 28, 1.3), (4300, 36, 0.7)]:
        pulse = (np.sin(2 * np.pi * rate * t) > 0.3).astype(float)
        burst = ((t % period) < 0.35).astype(float)
        out += np.sin(2 * np.pi * f * t) * pulse * burst * 0.08
    return out


def amb_river():
    out = np.zeros(int((AD + 1) * SR))
    for lo in [300, 600, 1200, 2400]:
        out += filt(noise(AD + 1), "bandpass", [lo, lo * 1.8], 2) * smooth_rand(AD + 1, 12, 0.2, 1)
    return out


def amb_sea():
    t = t_axis(AD + 1)
    swell = np.sin(np.pi * t / 7.0) ** 2
    low = filt(noise(AD + 1), "lowpass", 700) * (0.3 + swell)
    hiss = filt(noise(AD + 1), "highpass", 2500) * swell ** 3 * 0.4
    return low + hiss


def amb_cave():
    drone = filt(np.cumsum(noise(AD + 1)) * 0.01, "lowpass", 150)
    drone = norm(drone - np.mean(drone), 0.5)
    return reverb(drone + drips(AD + 1, 0.8) * 0.6, 2.0, 0.5)


def amb_castle():
    drone = filt(noise(AD + 1), "bandpass", [70, 300], 2) * 0.5
    steps = np.zeros_like(drone)
    for at in [2.0, 2.6, 3.2, 8.5, 9.1]:
        place(steps, thump(120, 0.2), at, 0.4)
    return reverb(drone + steps, 2.5, 0.5)


def amb_tavern():
    m = murmur(AD + 1, 7)
    clinks = np.zeros_like(m)
    for at in rng.uniform(0.5, AD, 6):
        place(clinks, metal_ping(rng.uniform(2500, 4000), 0.4, 0.08), at, 0.15)
    return m + clinks + crackle(AD + 1, 8) * 0.2


def amb_city():
    m = murmur(AD + 1, 12) * 0.8
    hooves = np.zeros_like(m)
    for k in range(10):
        place(hooves, thump(300, 0.08), 4 + k * 0.28, 0.3)
    return m + hooves


def amb_battle():
    m = murmur(AD + 1, 10) * 0.7
    for at in rng.uniform(0.3, AD, 14):
        place(m, metal_ping(rng.uniform(1000, 2000), 0.6, 0.15), at, rng.uniform(0.1, 0.3))
    t = t_axis(AD + 1)
    drums = np.zeros_like(m)
    for at in np.arange(0, AD, 0.75):
        place(drums, thump(60, 0.3), at, 0.5)
    return m + drums


def amb_fire():
    return filt(noise(AD + 1), "lowpass", 300) * 0.8 + crackle(AD + 1, 40)


def amb_snow():
    return filt(noise(AD + 1), "bandpass", [900, 2000], 2) * smooth_rand(AD + 1, 0.25, 0.2, 1) + filt(noise(AD + 1), "lowpass", 300) * 0.5


AMBIENCE = {
    "wind": amb_wind, "rain": amb_rain, "storm": amb_storm, "forest": amb_forest, "meadow": amb_meadow,
    "night": amb_night, "river": amb_river, "sea": amb_sea, "cave": amb_cave, "castle": amb_castle,
    "tavern": amb_tavern, "city": amb_city, "battle": amb_battle, "fire": amb_fire, "snow": amb_snow,
}


# ---------- действия ----------
def sfx_sword_clash():
    x = metal_ping(1300, 1.2, 0.35) + metal_ping(1750, 1.2, 0.3) * 0.6
    x += filt(noise(1.2), "highpass", 3000) * exp_env(1.2, 0.03) * 2
    return x


def sfx_sword_swing():
    return whoosh(0.4, 400, 2500, 600)


def sfx_punch():
    return thump(90, 0.3)


def sfx_fall():
    out = np.zeros(int(0.9 * SR))
    place(out, thump(60, 0.5), 0.0, 1.0)
    for k, at in enumerate([0.18, 0.3, 0.42]):
        place(out, thump(140 + 40 * k, 0.15), at, 0.3)
    return out


def sfx_arrow():
    out = np.zeros(int(0.8 * SR))
    place(out, whoosh(0.25, 2000, 4000, 2500), 0.0, 0.6)
    place(out, tone(320, 0.4, 0.06), 0.25, 1.0)
    place(out, thump(200, 0.2), 0.25, 0.5)
    return out


def sfx_fireball():
    d = 1.6
    roar = filt(noise(d), "lowpass", 900) * smooth_rand(d, 15, 0.5, 1)
    env = np.interp(t_axis(d), [0, 0.3, 1.0, d], [0, 1, 0.7, 0])
    return roar * env + whoosh(d, 300, 1500, 400) * 0.6 + crackle(d, 60) * env


def sfx_lightning():
    d = 2.8
    out = filt(noise(d), "highpass", 1000) * exp_env(d, 0.04) * 2
    out += rumble(d, 0.9) * 3
    return out


def sfx_thunder():
    out = np.zeros(int(3.5 * SR))
    place(out, rumble(3.3, 1.0), 0.1, 1.0)
    return out


def sfx_ice():
    d = 1.4
    out = np.zeros(int(d * SR))
    for at in np.sort(rng.uniform(0, 0.8, 25)):
        place(out, tone(rng.uniform(2500, 6500), 0.3, 0.08), at, rng.uniform(0.2, 0.6))
    out += filt(noise(d), "highpass", 5000) * exp_env(d, 0.4) * 0.3
    return out


def sfx_heal():
    out = np.zeros(int(2.0 * SR))
    for k, f in enumerate([523.25, 659.25, 783.99, 1046.5]):
        place(out, tone(f, 1.4, 0.5) + tone(f * 2, 1.4, 0.3) * 0.3, k * 0.12, 0.6)
    return out


def sfx_magic():
    d = 1.4
    out = tone(lambda t: 600 + 1400 * t / d + 30 * np.sin(2 * np.pi * 7 * t), d) * np.hanning(int(d * SR)) * 0.4
    for at in np.sort(rng.uniform(0, 1.1, 15)):
        place(out, tone(rng.uniform(3000, 7000), 0.2, 0.05), at, 0.3)
    return out


def sfx_explosion():
    d = 2.5
    n = int(d * SR)
    x = noise(d) * exp_env(d, 0.5)
    lo = filt(x, "lowpass", 2000) * 0.6 + filt(x, "lowpass", 300) * 2
    boom = tone(lambda t: 50 + 40 * np.exp(-t * 5), d, 0.6) * 1.5
    return lo + boom[:n]


def sfx_door_knock():
    out = np.zeros(int(1.0 * SR))
    for at in [0.0, 0.25, 0.5]:
        place(out, thump(180, 0.15) + filt(noise(0.15), "bandpass", [400, 1500]) * exp_env(0.15, 0.01), at)
    return out


def sfx_door_creak():
    d = 1.3
    t = t_axis(d)
    f = 280 + 120 * t / d + 15 * smooth_rand(d, 25, -1, 1)
    ph = 2 * np.pi * np.cumsum(f) / SR
    saw = 2 * ((ph / (2 * np.pi)) % 1) - 1
    gate = smooth_rand(d, 30, 0, 1) > 0.3
    return filt(saw * gate, "bandpass", [500, 3000], 2) * np.hanning(len(t))


def sfx_footsteps():
    out = np.zeros(int(2.2 * SR))
    for k in range(4):
        step = thump(110, 0.18) * 0.6 + filt(noise(0.18), "bandpass", [300, 2500]) * exp_env(0.18, 0.03)
        place(out, step, k * 0.5, 0.8 if k % 2 else 1.0)
    return out


def sfx_roar():
    d = 2.0
    t = t_axis(d)
    f = 75 + 20 * smooth_rand(d, 8, -1, 1)
    ph = 2 * np.pi * np.cumsum(f) / SR
    saw = 2 * ((ph / (2 * np.pi)) % 1) - 1
    env = np.interp(t, [0, 0.25, 1.4, d], [0, 1, 0.8, 0])
    growl = filt(saw, "lowpass", 900) + filt(noise(d), "bandpass", [200, 1200]) * 0.6
    return growl * env * smooth_rand(d, 20, 0.6, 1)


def sfx_wolf_howl():
    d = 2.8
    t = t_axis(d)
    f = np.interp(t, [0, 0.6, 2.0, d], [420, 720, 680, 520]) * (1 + 0.012 * np.sin(2 * np.pi * 5.5 * t))
    y = tone(lambda tt: f[: len(tt)], d) + tone(lambda tt: 2 * f[: len(tt)], d) * 0.25
    return y * np.interp(t, [0, 0.4, 2.2, d], [0, 1, 0.8, 0])


def sfx_owl():
    out = np.zeros(int(1.6 * SR))
    for at, dur in [(0.0, 0.35), (0.55, 0.6)]:
        h = tone(lambda t: 380 - 30 * t, dur) * np.hanning(int(dur * SR))
        place(out, h, at)
    return filt(out, "lowpass", 1200)


def sfx_bird():
    return bird_calls(2.0, 2.5)


def sfx_coins():
    out = np.zeros(int(1.0 * SR))
    for at in np.sort(rng.uniform(0, 0.5, 9)):
        place(out, metal_ping(rng.uniform(3500, 6000), 0.3, 0.06), at, rng.uniform(0.3, 1.0))
    return out


def sfx_splash():
    d = 1.2
    out = filt(noise(d), "bandpass", [300, 5000], 2) * exp_env(d, 0.15)
    for at in np.sort(rng.uniform(0.15, 0.9, 10)):
        place(out, chirp(400, rng.uniform(900, 1600), 0.05), at, 0.3)
    return out


def sfx_bell():
    ratios = [1.0, 2.0, 2.4, 3.0, 4.2]
    return sum(tone(330 * r, 3.5, 1.2 / (1 + i * 0.5)) / (1 + i) for i, r in enumerate(ratios))


def sfx_horse_snort():
    """Фырканье: шумный выдох с дрожанием губ."""
    d = 0.9
    t = t_axis(d)
    flutter = 0.55 + 0.45 * np.sin(2 * np.pi * 28 * t)
    breath = filt(noise(d), "bandpass", [150, 1800], 2) * flutter
    return breath * np.interp(t, [0, 0.05, 0.5, d], [0, 1, 0.6, 0])


def sfx_horse_gallop():
    out = np.zeros(int(2.0 * SR))
    for k in range(6):
        for off in (0.0, 0.09, 0.17):
            place(out, thump(250, 0.08), k * 0.32 + off, 0.7)
    return out


SFX = {name[4:]: fn for name, fn in globals().items() if name.startswith("sfx_")}


def write_wav(path: Path, x: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="перезаписать существующие файлы")
    args = ap.parse_args()
    made = 0
    for name, fn in AMBIENCE.items():
        p = AMB_DIR / f"{name}.wav"
        if p.exists() and not args.force:
            continue
        write_wav(p, norm(loopify(fn()), 0.5))
        made += 1
    for name, fn in SFX.items():
        p = SFX_DIR / f"{name}.wav"
        if p.exists() and not args.force:
            continue
        x = fn()
        fade = min(len(x), int(0.01 * SR))
        x[-fade:] *= np.linspace(1, 0, fade)
        write_wav(p, norm(x, 0.9))
        made += 1
    print(f"gen_sounds: создано {made} файлов (фон: {len(AMBIENCE)}, действия: {len(SFX)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
