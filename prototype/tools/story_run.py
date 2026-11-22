"""Прогон текста рассказа через настоящий движок — как живая речь — и отчёт «что прозвучало на какой фразе».

  python tools/story_run.py tests/stories/rybak.txt            # отчёт в консоль
  python tools/story_run.py tests/stories/*.txt --out report.md # в файл
  python tools/story_run.py tests/stories/rybak.txt --voice    # голосом: TTS-WAV → Vosk → движок

Без звука (NullAudio), с моделью смысла. Время — условное: слово ≈ 0,4 с (≈ 2,5 сл/с), пауза после фразы 0,8 с,
так задержки и звукооператор ведут себя как с рассказчиком. Фраза — до . ! ? … ; (как пауза в речи).
Для разбора ошибок: какие сцены, персонажи, действия, настроение сработали и что движок решил «тише».
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

WORD_S, PHRASE_PAUSE_S = 0.4, 0.8


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def clean_wikitext(raw: str) -> str:
    """Текст с Викитеки (wikitext) → обычный текст: без шаблонов, сносок, ударений и разметки."""
    t = re.sub(r"<ref[^>]*>.*?</ref>|<ref[^>]*/>", "", raw, flags=re.S)
    t = re.sub(r"\{\{Отексте.*?\n\}\}", "", t, flags=re.S)
    t = re.sub(r"\{\{(?:indent)\|\d+\|([^{}]*)\}\}", r"\1", t)
    t = re.sub(r"\{\{poemx1\|\|", "", t)
    t = re.sub(r"\{\{F1\|.*?\|\n", "", t, count=1, flags=re.S)
    t = re.sub(r"\|\}\}", "", t)
    t = re.sub(r"\{\{[^{}]*\}\}", "", t)
    t = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", t)
    t = re.sub(r"^==.*==\s*$", "", t, flags=re.M)
    t = re.sub(r"<[^>]+>", "", t)
    t = t.replace("'''", "").replace("''", "").replace("́", "").replace("&nbsp;", " ")
    t = re.sub(r"[ \t]+", " ", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def phrases(text: str) -> list[str]:
    """Фразы — как паузы рассказчика: по . ! ? … ;
    Перевод строки закрывает фразу, если следующая строка — со строчной буквы (так набирают в поле ввода:
    «жили были дед и баба⏎у самого синего моря»). Строки стиха (с заглавной) фразу не делят."""
    text = re.sub(r"([^\s.!?…;,:])[ \t]*\n+(?=[ \t]*[a-zа-яё])", r"\1.\n", text)
    flat = re.sub(r"\s+", " ", text)
    # конец фразы — и «…полетели?⟧ » (знак внутри закрывающей метки реплики)
    parts = re.split(r"(?<=[.!?…;])\s+|(?<=[.!?…;]⟧)\s+", flat)
    return [p.strip(" —–-«»\"") for p in parts if re.search(r"\w", p)]


def build(clock: Clock, log, embedder=None):
    from storyfx.actions import ActionMatcher, load_actions
    from storyfx.audio import NullAudio
    from storyfx.characters import CharacterTracker, load_characters
    from storyfx.engine import StoryEngine
    from storyfx.mixer import SoundMixer
    from storyfx.mood import load_moods, make_mood_tracker
    from storyfx.scenes import RuBertEmbedder, SceneTracker, load_scene_examples, load_scenes
    from storyfx.speech import load_speech_cues
    emb = embedder or RuBertEmbedder()
    scenes, overlays = load_scenes()
    moods, default = load_moods()
    return StoryEngine(
        actions=ActionMatcher(load_actions(), embedder=emb, clock=clock),
        scenes=SceneTracker(scenes, overlays, embedder=emb, examples=load_scene_examples()),
        audio=NullAudio(), log=log, clock=clock,
        moods=make_mood_tracker(moods, default, embedder=emb), music_on=True,
        characters=CharacterTracker(load_characters(), clock=clock),
        mixer=SoundMixer(clock=clock, mood=default),   # без muted.yaml: проверяем решения, а не выбор владельца
        speech_cues=load_speech_cues(),                 # голос: реплики по словам (у текста — кавычки)
    )


@dataclass
class PhraseResult:
    text: str
    log: list[str]                       # строки журнала, пока звучала фраза
    events: list[tuple[str, str]]        # события движка: ("sfx", id), ("char", id), ("scene", id), ("leave", id)…


def run(text: str, engine=None) -> list[PhraseResult]:
    """Прогнать текст. engine — готовый движок (тесты переиспользуют модель смысла), иначе создаётся."""
    from storyfx.asr import TextEvent
    from storyfx.textnorm import SPEECH_CLOSE, SPEECH_OPEN, mark_speech, speech_words
    clock = Clock()
    lines: list[str] = []
    eng = engine(clock, lines.append) if engine else build(clock, lines.append)
    out = []
    in_speech = False                        # реплика может продолжиться в следующей фразе
    for p in phrases(mark_speech(text)):
        lines.clear()
        start = len(eng.events)
        words, mask, in_speech = speech_words(p, in_speech)
        for i in range(1, len(words) + 1):
            eng.on_text(TextEvent(" ".join(words[:i]), False, tuple(mask[:i])))
            clock.t += WORD_S
        eng.on_text(TextEvent(" ".join(words), True, tuple(mask)))
        clock.t += PHRASE_PAUSE_S
        keep = [re.sub(r"^\[\s*[\d.]+s\]\s*", "", l) for l in lines if "фраза:" not in l]
        shown = p.replace(SPEECH_OPEN, "«").replace(SPEECH_CLOSE, "»")
        out.append(PhraseResult(shown, keep, list(eng.events[start:])))
    _finish(eng, clock, out, lines)
    return out


def _finish(eng, clock, out, lines) -> None:
    """Рассказ кончился: тишина, движок доигрывает отложенное (eng.tick) — в итог последней фразы."""
    start = len(eng.events)
    lines.clear()
    clock.t += 3.0
    eng.tick()
    if out and len(eng.events) > start:
        last = out[-1]
        last.log.extend(re.sub(r"^\[\s*[\d.]+s\]\s*", "", l) for l in lines)
        last.events.extend(eng.events[start:])


def run_wav(path: Path, engine=None, model_dir: Path | None = None) -> list[PhraseResult]:
    """Прогон ГОЛОСОМ: WAV → Vosk → движок, как с микрофоном (без кавычек и знаков, фразы — по паузам).
    Время — по записи. Фраза в отчёте — то, что Vosk отдал финальным результатом."""
    import wave

    from storyfx import config
    from storyfx.asr import VoskStream
    clock = Clock()
    lines: list[str] = []
    eng = engine(clock, lines.append) if engine else build(clock, lines.append)
    out, start = [], 0
    stream = VoskStream(model_dir) if model_dir else VoskStream()   # другая модель — для сравнения
    block = int(config.SAMPLE_RATE * config.BLOCK_SECONDS)

    def feed(events):
        nonlocal start
        for ev in events:
            eng.on_text(ev)
            if ev.final:
                keep = [re.sub(r"^\[\s*[\d.]+s\]\s*", "", l) for l in lines if "фраза:" not in l]
                out.append(PhraseResult(ev.text, keep, list(eng.events[start:])))
                lines.clear()
                start = len(eng.events)

    with wave.open(str(path), "rb") as w:
        while data := w.readframes(block):
            clock.t += len(data) / 2 / config.SAMPLE_RATE
            eng.tick()
            feed(stream.feed(data))
    feed(stream.flush())
    _finish(eng, clock, out, lines)
    return out


def story_wav(name: str) -> Path:
    return ROOT / "tests" / "wav" / "stories" / f"{name}.wav"


def report(name: str, result: list[PhraseResult]) -> str:
    rows = [f"## {name}", ""]
    for i, r in enumerate(result, 1):
        rows.append(f"{i}. {r.text}")
        rows += [f"    - {l}" for l in r.log]
    return "\n".join(rows) + "\n"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--wiki", action="store_true", help="файлы — wikitext с Викитеки: очистить разметку")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--vosk-model", type=Path, help="с --voice: другая модель Vosk (папка), по умолчанию — из config")
    ap.add_argument("--voice", action="store_true",
                    help="голосом: tests/wav/stories/<имя>.wav через Vosk (сделать: make_test_wavs.py --stories)")
    args = ap.parse_args()
    parts = []
    for f in args.files:
        if args.voice:
            parts.append(report(f"{f.stem} (голос)", run_wav(story_wav(f.stem), model_dir=args.vosk_model)))
            continue
        text = f.read_text(encoding="utf-8")
        if args.wiki:
            text = clean_wikitext(text)
        parts.append(report(f.stem, run(text)))
    doc = "\n".join(parts)
    if args.out:
        args.out.write_text(doc, encoding="utf-8")
        print(f"отчёт: {args.out}")
    else:
        print(doc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
