"""Озвучивает сценарии tests/scenarios.yaml голосом Windows TTS в WAV 16 кГц моно.

Запуск:  python tools/make_test_wavs.py [--force] [--voice "Microsoft Irina Desktop"]
Результат: tests/wav/<сценарий>.wav
  --stories: ещё и сказки tests/stories/*.txt → tests/wav/stories/<имя>.wav (прогон голосом:
  tools/story_run.py --voice). Фразы — как их делит story_run (паузы чтеца), по одной на строку.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "tests" / "scenarios.yaml"
OUT_DIR = ROOT / "tests" / "wav"
STORIES_DIR = ROOT / "tests" / "stories"

PS_SCRIPT = r"""
param([string]$TextFile, [string]$OutFile, [string]$Voice)
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.SelectVoice($Voice)
$s.Rate = 0
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$s.SetOutputToWaveFile($OutFile, $fmt)
$s.Speak([IO.File]::ReadAllText($TextFile, [Text.Encoding]::UTF8))
$s.Dispose()
"""


def synth(text: str, out: Path, voice: str) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        txt = Path(td) / "t.txt"
        ps1 = Path(td) / "tts.ps1"
        txt.write_text(text, encoding="utf-8")
        ps1.write_text(PS_SCRIPT, encoding="utf-8-sig")
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1),
             "-TextFile", str(txt), "-OutFile", str(out), "-Voice", voice],
            check=True,
        )


def story_wav(name: str) -> Path:
    return OUT_DIR / "stories" / f"{name}.wav"


def make_stories(voice: str, force: bool = False) -> int:
    sys.path.insert(0, str(ROOT / "tools"))
    from story_run import phrases          # те же фразы, что в текстовом прогоне: точка = пауза чтеца
    made = 0
    for f in sorted(STORIES_DIR.glob("*.txt")):
        out = story_wav(f.stem)
        if out.exists() and not force:
            continue
        synth("\n".join(phrases(f.read_text(encoding="utf-8"))), out, voice)
        made += 1
    return made


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--voice", default="Microsoft Irina Desktop")
    ap.add_argument("--stories", action="store_true", help="озвучить и сказки tests/stories/*.txt")
    args = ap.parse_args()
    scenarios = yaml.safe_load(SCENARIOS.read_text(encoding="utf-8"))
    made = 0
    for name, sc in scenarios.items():
        out = OUT_DIR / f"{name}.wav"
        if out.exists() and not args.force:
            continue
        synth(sc["text"], out, args.voice)
        made += 1
    if args.stories:
        made += make_stories(args.voice, args.force)
    print(f"make_test_wavs: создано {made} WAV в {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
