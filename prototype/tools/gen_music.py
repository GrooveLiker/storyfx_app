"""Синтез фоновой музыки: 4 зацикленные петли по настроению (свои, без лицензий).

Запуск:  python tools/gen_music.py [--force]      → sounds/music/<calm|cheerful|tense|action>.wav

Петля без щелчка на стыке: ноты раскладываются на один период, рендерятся три повтора подряд,
берётся средний — хвосты нот и эхо из конца петли уже звучат в её начале.
Музыка тихая и простая намеренно: она под рассказом, а не вместо него.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gen_sounds import SR, filt, write_wav  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MUSIC_DIR = ROOT / "sounds" / "music"
rng = np.random.default_rng(7)

NOTE = {n: i for i, n in enumerate(["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"])}


def hz(name: str) -> float:
    """'A4' → 440, 'C#3' → …"""
    n, octave = name[:-1], int(name[-1])
    return 440.0 * 2 ** ((NOTE[n] + 12 * (octave + 1) - 69) / 12)


def chord(root: str, kind: str = "maj", octave: int = 3) -> list[float]:
    steps = {"maj": [0, 4, 7], "min": [0, 3, 7], "maj7": [0, 4, 7, 11], "min7": [0, 3, 7, 10]}[kind]
    f0 = hz(f"{root}{octave}")
    return [f0 * 2 ** (s / 12) for s in steps]


# ---------- инструменты (возвращают моно-массив) ----------
def _t(dur: float) -> np.ndarray:
    return np.arange(int(dur * SR)) / SR


def adsr(n: int, a: float, r: float) -> np.ndarray:
    env = np.ones(n)
    na, nr = min(n, int(a * SR)), min(n, int(r * SR))
    env[:na] = np.linspace(0, 1, na)
    if nr:
        env[-nr:] *= np.linspace(1, 0, nr)
    return env


def pad(freqs: list[float], dur: float, bright: float = 1200) -> np.ndarray:
    t = _t(dur)
    x = np.zeros_like(t)
    for f in freqs:
        for det in (-0.003, 0.0, 0.003):          # три слегка расстроенных голоса — «объём»
            ph = 2 * np.pi * f * (1 + det) * t + rng.uniform(0, 6.28)
            x += np.sin(ph) + 0.3 * np.sin(2 * ph) + 0.15 * np.sin(3 * ph)
    x = filt(x, "lowpass", bright, 2)
    return x * adsr(len(t), min(1.5, dur / 3), min(1.5, dur / 3)) / (3 * len(freqs))


def pluck(f: float, dur: float = 0.8, decay: float = 4.0) -> np.ndarray:
    t = _t(dur)
    x = sum(np.sin(2 * np.pi * f * k * t) / k ** 2 for k in (1, 2, 3, 4))
    return x * np.exp(-t * decay) * adsr(len(t), 0.004, 0.05)


def bass(f: float, dur: float, decay: float = 3.0) -> np.ndarray:
    t = _t(dur)
    x = np.sin(2 * np.pi * f * t) + 0.25 * np.sign(np.sin(2 * np.pi * f * t))
    return filt(x, "lowpass", 600, 2) * np.exp(-t * decay) * adsr(len(t), 0.005, 0.05)


def stab(freqs: list[float], dur: float = 0.18) -> np.ndarray:
    """Короткий аккорд пилой — «струнные стаккато»."""
    t = _t(dur)
    x = sum(2 * ((f * t) % 1) - 1 for f in freqs)
    return filt(x, "lowpass", 2500, 2) * np.exp(-t * 12) * adsr(len(t), 0.003, 0.03) / len(freqs)


def kick(dur: float = 0.35) -> np.ndarray:
    t = _t(dur)
    f = 45 + 80 * np.exp(-t * 30)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 9)


def snare(dur: float = 0.2) -> np.ndarray:
    t = _t(dur)
    n = filt(rng.standard_normal(len(t)), "bandpass", [1500, 6000], 2)
    return (n * 0.8 + np.sin(2 * np.pi * 190 * t) * 0.5) * np.exp(-t * 22)


def hat(dur: float = 0.05) -> np.ndarray:
    t = _t(dur)
    return filt(rng.standard_normal(len(t)), "highpass", 7000, 2) * np.exp(-t * 70)


def bell(f: float, dur: float = 2.5) -> np.ndarray:
    t = _t(dur)
    x = sum(a * np.sin(2 * np.pi * f * r * t) for r, a in [(1, 1), (2.76, 0.5), (5.4, 0.25)])
    return x * np.exp(-t * 2.5) * adsr(len(t), 0.002, 0.1)


def tremolo(freqs: list[float], dur: float, rate: float = 7.0) -> np.ndarray:
    t = _t(dur)
    x = sum(np.sin(2 * np.pi * f * t) for f in freqs) / len(freqs)
    return x * (0.6 + 0.4 * np.sin(2 * np.pi * rate * t)) * adsr(len(t), dur / 2, dur / 2)


def xylo(f: float, dur: float = 0.5) -> np.ndarray:
    """Ксилофон: яркий удар, обертон ×3.93, быстрое затухание."""
    t = _t(dur)
    x = np.sin(2 * np.pi * f * t) + 0.35 * np.sin(2 * np.pi * f * 3.93 * t) * np.exp(-t * 30)
    return x * np.exp(-t * 9) * adsr(len(t), 0.001, 0.03)


def saw_ens(freqs: list[float], dur: float, cutoff: float = 3000, voices: int = 5) -> np.ndarray:
    """Ансамбль расстроенных пил — «струнные»."""
    t = _t(dur)
    x = np.zeros_like(t)
    for f in freqs:
        for v in range(voices):
            fd = f * (1 + (v - voices // 2) * 0.004)
            x += 2 * ((fd * t + rng.uniform()) % 1) - 1
    return filt(x, "lowpass", cutoff, 2) / (len(freqs) * voices)


def strings_tremolo(freqs: list[float], dur: float, rate: float = 11.0) -> np.ndarray:
    """Струнные тремоло с нарастанием и спадом — классика «сейчас что-то будет»."""
    t = _t(dur)
    x = saw_ens(freqs, dur, 2500)
    swell = np.sin(np.pi * t / dur) ** 2
    return x * (0.55 + 0.45 * np.sin(2 * np.pi * rate * t)) * swell


def brass(freqs: list[float], dur: float = 0.7) -> np.ndarray:
    """«Медь»: пила, у которой яркость резко нарастает и гаснет."""
    t = _t(dur)
    dark, bright = saw_ens(freqs, dur, 600, 3), saw_ens(freqs, dur, 3500, 3)
    open_ = np.exp(-t * 6)
    return (dark * (1 - open_) + bright * open_) * adsr(len(t), 0.02, 0.15)


def taiko(dur: float = 0.9) -> np.ndarray:
    t = _t(dur)
    f = 55 + 60 * np.exp(-t * 20)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 5)
    skin = filt(rng.standard_normal(len(t)), "lowpass", 900, 2) * np.exp(-t * 35)
    return body + skin * 0.6


def clap(dur: float = 0.15) -> np.ndarray:
    t = _t(dur)
    n = filt(rng.standard_normal(len(t)), "bandpass", [900, 2500], 2)
    env = sum(np.exp(-np.clip(t - d, 0, None) * 60) * (t >= d) for d in (0, 0.01, 0.02))
    return n * env


def tambourine(dur: float = 0.12) -> np.ndarray:
    t = _t(dur)
    jingle = sum(np.sin(2 * np.pi * f * t) for f in (6200, 7400, 8900)) * 0.3
    return (filt(rng.standard_normal(len(t)), "highpass", 6000, 2) + jingle) * np.exp(-t * 35)


def melody(L: "Loop", start_beat: float, notes: list[str | None], step: float, voice, gain: float) -> None:
    """notes — по одной на шаг (step долей); None — пауза."""
    for i, n in enumerate(notes):
        if n:
            L.add(start_beat + i * step, voice(hz(n)), gain)


# ---------- сборка петли ----------
class Loop:
    def __init__(self, bpm: float, bars: int, beats_per_bar: int = 4):
        self.beat = 60.0 / bpm
        self.n = int(round(bars * beats_per_bar * self.beat * SR))
        self.events: list[tuple[int, np.ndarray, float]] = []

    def add(self, beat_pos: float, sound: np.ndarray, gain: float = 1.0) -> None:
        self.events.append((int(round(beat_pos * self.beat * SR)) % self.n, sound, gain))

    def render(self) -> np.ndarray:
        out = np.zeros(self.n * 3 + max(len(s) for _, s, _ in self.events))
        for rep in range(3):
            for at, s, g in self.events:
                i = rep * self.n + at
                out[i:i + len(s)] += s * g
        return out[self.n:2 * self.n]


def echo(x: np.ndarray, delay_s: float, fb: float, mix: float) -> np.ndarray:
    """Эхо по кругу (петля периодична, хвост заворачивается в начало)."""
    d = int(delay_s * SR)
    y = x.copy()
    tap = x.copy()
    for _ in range(6):
        tap = np.roll(tap, d) * fb
        y += tap * mix
    return y


# ---------- 4 настроения ----------
def music_calm() -> np.ndarray:
    """Спокойная: 64 уд/мин, мягкие аккорды C–Am–F–G и неторопливый перебор."""
    L = Loop(64, 8)
    prog = [("C", "maj7"), ("A", "min7"), ("F", "maj7"), ("G", "maj")] * 2
    for bar, (r, k) in enumerate(prog):
        L.add(bar * 4, pad(chord(r, k, 3), 4 * L.beat + 1.5), 0.9)
        notes = chord(r, k, 4)
        for i, step in enumerate([0, 1, 2, 1]):
            L.add(bar * 4 + i, pluck(notes[step % len(notes)], 1.6, 2.5), 0.25)
    return echo(L.render(), L.beat * 0.75, 0.5, 0.35)


def music_cheerful() -> np.ndarray:
    """Весёлая: 132 уд/мин, до мажор, своя мелодия на ксилофоне, бас «умпа» как у польки,
    хлопки на 2 и 4, бубен на слабые восьмые."""
    L = Loop(132, 8)
    prog = [("C", "maj"), ("F", "maj"), ("G", "maj"), ("C", "maj"),
            ("C", "maj"), ("F", "maj"), ("G", "maj"), ("C", "maj")]
    tune = [  # по восьмой на ноту, 8 на такт
        ["E5", None, "G5", "E5", "C5", None, "D5", "E5"],
        ["F5", None, "A5", "F5", "C5", None, "D5", "F5"],
        ["D5", None, "G5", "F5", "E5", None, "D5", "B4"],
        ["C5", "E5", "G5", "C6", None, None, "G5", None],
        ["E5", "F5", "G5", "E5", "C5", None, "E5", "G5"],
        ["A5", None, "F5", "A5", "C6", None, "A5", "F5"],
        ["D5", "E5", "F5", "D5", "B4", "C5", "D5", "B4"],
        ["C5", None, "G4", None, "C5", None, None, None],
    ]
    for bar, (r, k) in enumerate(prog):
        b = bar * 4
        lo, hi = chord(r, k, 2), chord(r, k, 4)
        for beat in (0, 2):                                   # «ум» — бас
            L.add(b + beat, bass(lo[0] if beat == 0 else lo[2], 0.3, 10), 0.55)
        for beat in (1, 3):                                   # «па» — короткий аккорд
            for f in hi:
                L.add(b + beat, pluck(f, 0.25, 14), 0.12)
            L.add(b + beat, clap(), 0.22)
        for i in range(8):
            L.add(b + i * 0.5, tambourine(), 0.10 if i % 2 else 0.04)
        melody(L, b, tune[bar], 0.5, lambda f: xylo(f, 0.45), 0.42)
    return echo(L.render(), L.beat * 0.75, 0.25, 0.15)


def music_tense() -> np.ndarray:
    """Тревожная: 76 уд/мин, ре минор. Низкий гул, струнные тремоло на диссонансе (малая секунда),
    которые нарастают и стихают; бас крадётся по полутонам; сердцебиение; глухой удар раз в 4 такта."""
    L = Loop(76, 8)
    L.add(0, pad([hz("D1"), hz("D2"), hz("D#2")], 16 * L.beat + 2, 350), 1.3)
    L.add(16, pad([hz("D1"), hz("D2"), hz("C#2")], 16 * L.beat + 2, 350), 1.3)
    for bar, cluster in [(0, ["D5", "D#5"]), (2, ["A4", "A#4"]), (4, ["D5", "D#5", "G#5"]), (6, ["C#5", "D5"])]:
        L.add(bar * 4, strings_tremolo([hz(n) for n in cluster], 8 * L.beat), 0.55)
    creep = ["D3", None, "D#3", None, "D3", None, "C#3", None]     # крадущиеся шаги
    for bar in range(8):
        melody(L, bar * 4, creep, 0.5, lambda f: pluck(f, 0.5, 9), 0.45)
        L.add(bar * 4, kick(0.3), 0.6)                               # тук-тук
        L.add(bar * 4 + 0.3, kick(0.3), 0.4)
    for at in (0, 16):
        L.add(at, taiko(1.5), 0.7)
    for pos, note in [(10, "G#5"), (26.5, "G#5")]:                    # тритон к D — неуютно
        L.add(pos, bell(hz(note), 3.0), 0.15)
    return echo(L.render(), L.beat * 1.5, 0.5, 0.3)


def music_action() -> np.ndarray:
    """Динамичная (бой, погоня): 150 уд/мин, ре минор. Струнные шестнадцатыми, «медь» на сильную долю,
    большие барабаны тайко, малый на 2 и 4, дробь в конце каждых 4 тактов."""
    L = Loop(150, 8)
    prog = [("D", "min"), ("D", "min"), ("A#", "maj"), ("A", "maj"),
            ("D", "min"), ("D", "min"), ("G", "min"), ("A", "maj")]
    ost = [0, 0, 7, 0, 0, 0, 8, 7, 0, 0, 7, 0, 12, 10, 8, 7]          # полутоны от тоники, по 1/16
    for bar, (r, k) in enumerate(prog):
        b = bar * 4
        f0 = hz(f"{r}3")
        for i, st in enumerate(ost):
            L.add(b + i * 0.25, stab([f0 * 2 ** (st / 12)], 0.12), 0.35)
        L.add(b, brass(chord(r, k, 3), 1.0), 0.6)
        L.add(b + 2.5, brass(chord(r, k, 3), 0.5), 0.4)
        for i in range(8):
            L.add(b + i * 0.5, bass(hz(f"{r}1"), 0.2, 12), 0.5)
        for i in (0, 1.5, 2, 3):
            L.add(b + i, taiko(), 0.8)
        for i in (1, 3):
            L.add(b + i, snare(), 0.4)
        if bar % 4 == 3:                                               # дробь перед повтором
            for i in range(8):
                L.add(b + 2 + i * 0.25, snare(0.12), 0.2 + i * 0.03)
    return echo(L.render(), L.beat * 0.5, 0.2, 0.12)


MUSIC = {"calm": music_calm, "cheerful": music_cheerful, "tense": music_tense, "action": music_action}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="перезаписать существующие файлы")
    args = ap.parse_args()
    made = 0
    for name, fn in MUSIC.items():
        p = MUSIC_DIR / f"{name}.wav"
        if p.exists() and not args.force:
            continue
        x = fn()
        x = x - np.mean(x)          # без фильтров после нарезки: они дали бы щелчок на стыке
        # одинаковая средняя громкость у всех настроений (иначе смена — провал/скачок), пик не выше 0,95
        gain = min(0.10 / (np.sqrt(np.mean(x ** 2)) + 1e-9), 0.95 / (np.max(np.abs(x)) + 1e-9))
        write_wav(p, x * gain)
        made += 1
        print(f"  {name}: {len(x) / SR:.1f} с")
    print(f"gen_music: создано {made} файлов в {MUSIC_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
