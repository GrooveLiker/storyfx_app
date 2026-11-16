"""Сравнение моделей Vosk на сказках голосом: сколько слов распознано неверно и сколько проверок
из tests/story_expectations.yaml не проходит.

  python tools/compare_asr.py models/vosk-model-small-ru-0.22 models/vosk-model-ru-0.42

WAV — tests/wav/stories (tools/make_test_wavs.py --stories). Всё локально.
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tools"), str(ROOT / "tests")]

import story_run  # noqa: E402


def words(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower().replace("ё", "е"))


def wer(ref: list[str], hyp: list[str]) -> float:
    """Доля ошибок распознавания по словам (замены + пропуски + вставки) / слов в тексте."""
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return prev[-1] / max(1, len(ref))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="+", type=Path)
    args = ap.parse_args()
    import test_stories                                  # те же проверки, что в pytest
    from storyfx.scenes import RuBertEmbedder
    emb = RuBertEmbedder()
    names = list(test_stories.SPEC["stories"])
    for model in args.models:
        t0 = time.perf_counter()
        results, rows = {}, []
        for n in names:
            results[n] = story_run.run_wav(story_run.story_wav(n), model_dir=model,
                                           engine=lambda c, log: story_run.build(c, log, embedder=emb))
            ref = words(" ".join(story_run.phrases((ROOT / "tests" / "stories" / f"{n}.txt").read_text(encoding="utf-8"))))
            hyp = words(" ".join(r.text for r in results[n]))
            rows.append((n, wer(ref, hyp)))
        failed = []
        for n, check_id, check in test_stories.checks():
            try:
                test_stories.test_story("voice", n, check, lambda mode, name: results[name])
            except AssertionError:
                failed.append(f"{n}:{check_id}")
        print(f"\n== {model.name}  ({time.perf_counter() - t0:.0f} с)")
        print("  ошибок распознавания по словам: " + ", ".join(f"{n} {w:.0%}" for n, w in rows))
        print(f"  проверок не прошло: {len(failed)} из {len(test_stories.checks())}")
        for f in failed:
            print(f"    - {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
