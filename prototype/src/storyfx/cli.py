"""Командная строка прототипа. Примеры — CLAUDE.md, раздел «Запуск»."""
from __future__ import annotations

import argparse
import sys
import threading
from pathlib import Path

from .asr import mic_events, stdin_lines, text_events, wav_events
from .audio import NullAudio
from .engine import StoryEngine
from .characters import CharacterTracker, load_characters
from .mixer import SoundMixer
from .muted import load_muted
from .mood import load_moods, make_mood_tracker
from .scenes import SceneTracker, load_scene_examples, load_scenes
from .actions import ActionMatcher, load_actions
from .speech import load_speech_cues


MUSIC_TOGGLE = {"!музыка", "!music"}


def build_engine(audio, use_embedder: bool = True, log=print, music: bool = True) -> StoryEngine:
    import time
    embedder = None
    if use_embedder:
        from .scenes import RuBertEmbedder
        log("Загрузка модели смысла rubert-tiny2…")
        embedder = RuBertEmbedder()
    scenes, overlays = load_scenes()
    moods, default = load_moods()
    return StoryEngine(
        actions=ActionMatcher(load_actions(), embedder=embedder),
        scenes=SceneTracker(scenes, overlays, embedder=embedder,
                            examples=load_scene_examples() if embedder is not None else None),
        audio=audio,
        log=log,
        moods=make_mood_tracker(moods, default, embedder=embedder),
        music_on=music,
        characters=CharacterTracker(load_characters()),
        mixer=SoundMixer(clock=time.monotonic, mood=default),
        speech_cues=load_speech_cues(),
        muted=load_muted(),
    )


def with_music_toggle(lines, engine: StoryEngine):
    """Строка «!музыка» в режиме --text включает/выключает музыку и дальше не передаётся."""
    for line in lines:
        if line.strip().lower() in MUSIC_TOGGLE:
            engine.set_music_enabled(not engine.music_on)
            continue
        yield line


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="storyfx", description="Живая озвучка рассказа (прототип)")
    src =ap.add_mutually_exclusive_group()
    src.add_argument("--text", action="store_true", help="вводить текст с клавиатуры вместо микрофона")
    src.add_argument("--wav", type=Path, help="распознать WAV-файл (16 кГц, моно)")
    ap.add_argument("--fast", action="store_true", help="WAV/текст без пауз реального времени")
    ap.add_argument("--no-audio", action="store_true", help="не играть звук, только печатать события")
    ap.add_argument("--no-embed", action="store_true", help="сцены только по ключевым словам (без rubert-tiny2)")
    ap.add_argument("--no-music", action="store_true", help="без фоновой музыки (в --text: «!музыка» — вкл/выкл)")
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
        audio = PygameAudio()

    engine = build_engine(audio, use_embedder=not args.no_embed, music=not args.no_music)

    if args.wav:
        events = wav_events(args.wav, realtime=not args.fast)
    elif args.text:
        print("Пишите текст; «!музыка» — включить/выключить музыку.")
        events = text_events(with_music_toggle(stdin_lines(), engine), word_delay=0 if args.fast else 0.4)   # ≈ 2,5 сл/с — обычный темп рассказа
    else:
        print("Слушаю микрофон… (Ctrl+C — выход). Лучше в наушниках, чтобы микрофон не слышал звуки.")
        events = mic_events(args.device)

    # Отложенные голоса персонажей доигрываются и в тишине (engine.tick) — отдельный поток раз в 0,3 с.
    lock, stop = threading.Lock(), threading.Event()

    def ticker():
        while not stop.wait(0.3):
            with lock:
                engine.tick()

    threading.Thread(target=ticker, daemon=True).start()
    try:
        for ev in events:
            with lock:
                engine.on_text(ev)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        audio.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
