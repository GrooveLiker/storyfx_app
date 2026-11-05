"""Командная строка прототипа. Примеры — CLAUDE.md, раздел «Запуск»."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .asr import mic_events, stdin_lines, text_events, wav_events
from .audio import NullAudio
from .engine import StoryEngine
from .scenes import SceneTracker, load_scenes
from .triggers import TriggerMatcher, load_triggers


def build_engine(mode: str, audio, use_embedder: bool = True, log=print) -> StoryEngine:
    embedder = None
    if use_embedder:
        from .scenes import RuBertEmbedder
        log("Загрузка модели смысла rubert-tiny2…")
        embedder = RuBertEmbedder()
    scenes, overlays = load_scenes()
    return StoryEngine(
        triggers=TriggerMatcher(load_triggers(), mode=mode),
        scenes=SceneTracker(scenes, overlays, embedder=embedder, mode=mode),
        audio=audio,
        log=log,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="storyfx", description="Живая озвучка рассказа (прототип)")
    ap.add_argument("--mode", choices=["dnd", "kids"], default="dnd", help="dnd — всё; kids — без страшных звуков")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--text", action="store_true", help="вводить текст с клавиатуры вместо микрофона")
    src.add_argument("--wav", type=Path, help="распознать WAV-файл (16 кГц, моно)")
    ap.add_argument("--fast", action="store_true", help="WAV/текст без пауз реального времени")
    ap.add_argument("--no-audio", action="store_true", help="не играть звук, только печатать события")
    ap.add_argument("--no-embed", action="store_true", help="сцены только по ключевым словам (без rubert-tiny2)")
    ap.add_argument("--device", type=int, help="номер микрофона (см. --list-devices)")
    ap.add_argument("--list-devices", action="store_true")
    args = ap.parse_args(argv)

    if args.list_devices:
        import sounddevice as sd
        print(sd.query_devices())
        return 0

    if args.no_audio:
        audio = NullAudio()
    else:
        from .audio import PygameAudio
        audio = PygameAudio(mode=args.mode)

    engine = build_engine(args.mode, audio, use_embedder=not args.no_embed)

    if args.wav:
        events = wav_events(args.wav, realtime=not args.fast)
    elif args.text:
        events = text_events(stdin_lines(), word_delay=0 if args.fast else 0.15)
    else:
        print("Слушаю микрофон… (Ctrl+C — выход). Лучше в наушниках, чтобы микрофон не слышал звуки.")
        events = mic_events(args.device)

    try:
        for ev in events:
            engine.on_text(ev)
    except KeyboardInterrupt:
        pass
    finally:
        audio.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
