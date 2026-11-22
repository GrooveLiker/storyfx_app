"""Точность сцен на размеченных сказках (задача 25): доля фраз, на которых играет фон того места, где герой.

  python tools/scene_eval.py                 # все сказки из tests/scene_labels.yaml, текстом
  python tools/scene_eval.py --voice         # голосом (TTS-WAV → Vosk; WAV: make_test_wavs.py --stories)
  python tools/scene_eval.py --misses        # плюс фразы с ошибкой

Сцена фразы — та, что играет после её конца (смены внутри фразы видны слушателю раньше — это допустимо).
Голосом фразы Vosk не совпадают с размеченными: фраза Vosk сопоставляется с размеченной по доле слов от начала сказки.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))
import story_run  # noqa: E402

LABELS = ROOT / "tests" / "scene_labels.yaml"
STORIES = ROOT / "tests" / "stories"
UNKNOWN = "?"


def load_labels(path: Path = LABELS) -> dict[str, list]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))["stories"]


def text_phrases(name: str) -> list[str]:
    """Фразы сказки — ровно как их режет story_run.run (с разметкой реплик), без знаков реплик."""
    from storyfx.textnorm import SPEECH_CLOSE, SPEECH_OPEN, mark_speech
    raw = (STORIES / f"{name}.txt").read_text(encoding="utf-8")
    return [p.replace(SPEECH_OPEN, "").replace(SPEECH_CLOSE, "") for p in story_run.phrases(mark_speech(raw))]


def expand(name: str, segments: list) -> list[str]:
    """Отрезки разметки → сцена каждой фразы. Сверяет начало фраз: деление на фразы не должно съехать."""
    text = text_phrases(name)
    out = [UNKNOWN] * len(text)
    for k, (start, scene, head) in enumerate(segments):
        phrase = text[start - 1]
        if not phrase.lstrip(" «—-").startswith(head):
            raise ValueError(f"{name}: фраза {start} начинается не с «{head}»: «{phrase[:40]}»")
        end = segments[k + 1][0] - 1 if k + 1 < len(segments) else len(text)
        for i in range(start - 1, end):
            out[i] = scene
    return out


def played(result) -> list[str | None]:
    """Какая сцена играет после каждой фразы прогона."""
    cur, out = None, []
    for r in result:
        for kind, sid in r.events:
            if kind == "scene":
                cur = sid
        out.append(cur)
    return out


def align_voice(name: str, result) -> list[int]:
    """Фраза Vosk → номер размеченной фразы (с 0) по доле слов от начала сказки."""
    text = text_phrases(name)
    cum, total = [], 0
    for p in text:
        total += len(p.split())
        cum.append(total)
    heard = [len(r.text.split()) for r in result]
    n_heard = max(1, sum(heard))
    out, seen = [], 0
    for h in heard:
        seen += h
        pos = seen / n_heard * total
        out.append(next((i for i, c in enumerate(cum) if c >= pos - 0.5), len(text) - 1))
    return out


def score(name: str, result, labels: list[str], voice: bool = False):
    """→ (верно, всего, ошибки [(номер, текст, надо, играло)])."""
    scenes = played(result)
    idx = align_voice(name, result) if voice else list(range(len(result)))
    ok = n = 0
    misses = []
    for k, (i, got) in enumerate(zip(idx, scenes)):
        want = labels[i]
        if want == UNKNOWN:
            continue
        n += 1
        if got in want.split("|"):
            ok += 1
        else:
            misses.append((k + 1, result[k].text, want, got))
    return ok, n, misses


def evaluate(engine=None, voice: bool = False, names: list[str] | None = None):
    """Все размеченные сказки → {имя: (верно, всего, ошибки)}. engine — как в story_run.run."""
    out = {}
    for name, segments in load_labels().items():
        if names and name not in names:
            continue
        labels = expand(name, segments)
        if voice and not story_run.story_wav(name).exists():
            print(f"{name}: нет WAV — tools/make_test_wavs.py --stories")
            continue
        if voice:
            result = story_run.run_wav(story_run.story_wav(name), engine=engine)
        else:
            result = story_run.run((STORIES / f"{name}.txt").read_text(encoding="utf-8"), engine=engine)
        out[name] = score(name, result, labels, voice)
    return out


def summary(res: dict) -> float:
    ok = sum(r[0] for r in res.values())
    n = sum(r[1] for r in res.values())
    return ok / max(1, n)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*", help="только эти сказки")
    ap.add_argument("--voice", action="store_true")
    ap.add_argument("--misses", action="store_true")
    args = ap.parse_args()
    from storyfx.scenes import RuBertEmbedder
    emb = RuBertEmbedder()
    res = evaluate(engine=lambda c, log: story_run.build(c, log, embedder=emb), voice=args.voice, names=args.names)
    for name, (ok, n, misses) in res.items():
        print(f"{name:12} {ok:4}/{n:<4} {ok / max(1, n):5.0%}")
        if args.misses:
            for k, text, want, got in misses:
                print(f"    {k:3}. надо {want:10} играло {str(got):10} {text[:70]}")
    print(f"{'ИТОГО':12} {summary(res):5.0%}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
