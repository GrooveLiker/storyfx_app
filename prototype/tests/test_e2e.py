"""Сквозные проверки с настоящими моделями. Запуск: pytest -m slow"""
import time
from pathlib import Path

import pytest

from conftest import TESTS, check_expectations, feed_text, make_engine
from storyfx import config

pytestmark = pytest.mark.slow
WAV_DIR = TESTS / "wav"


@pytest.fixture(scope="module")
def embedder():
    from storyfx.scenes import RuBertEmbedder
    return RuBertEmbedder()


def test_scenarios_text_with_embedder(triggers, scene_data, scenarios, clock, embedder):
    errors = []
    for name, sc in scenarios.items():
        eng = make_engine(sc["mode"], triggers, scene_data, clock, embedder)
        feed_text(eng, sc["text"], clock)
        errors += check_expectations(name, sc, eng.events)
    assert not errors, "\n".join(errors)


@pytest.mark.parametrize("text,expected", [
    ("путники долго пробирались сквозь бурелом, над головой шумели сосны и пели птицы", "forest"),
    ("корабль качало на волнах, солёные брызги летели на палубу", "sea"),
    ("с потолка капала вода, и каждый шаг отдавался гулким эхом в сыром туннеле", "cave"),
    ("за столами пили эль и громко смеялись, трактирщик протирал кружки", "tavern"),
])
def test_embedder_guesses_scene(scene_data, embedder, text, expected):
    from storyfx.scenes import SceneTracker
    scenes, overlays = scene_data
    t = SceneTracker(list(scenes), list(overlays), embedder=embedder)
    t._words = text.split()
    t.evaluate()
    best = max(t.last_scores, key=t.last_scores.get)
    assert best == expected, f"{best} вместо {expected}: {sorted(t.last_scores.items(), key=lambda kv: -kv[1])[:3]}"


def test_scene_eval_is_fast(scene_data, embedder):
    from storyfx.scenes import SceneTracker
    scenes, overlays = scene_data
    t = SceneTracker(list(scenes), list(overlays), embedder=embedder)
    t._words = ("герои шли по лесу " * 10).split()
    t0 = time.perf_counter()
    for _ in range(5):
        t.evaluate()
    per_call = (time.perf_counter() - t0) / 5
    assert per_call < 0.2, f"оценка сцены {per_call * 1000:.0f} мс — слишком медленно"


def test_wav_through_vosk(triggers, scene_data, scenarios, clock, embedder):
    from storyfx.asr import wav_events
    if not config.VOSK_MODEL_DIR.exists():
        pytest.fail("нет модели Vosk — запустите init.ps1")
    missing = [n for n in scenarios if not (WAV_DIR / f"{n}.wav").exists()]
    if missing:
        pytest.fail(f"нет тестовых WAV {missing} — запустите tools/make_test_wavs.py")
    errors, transcripts = [], []
    for name, sc in scenarios.items():
        eng = make_engine(sc["mode"], triggers, scene_data, clock, embedder)
        finals = []
        for ev in wav_events(WAV_DIR / f"{name}.wav", realtime=False):
            clock.advance(0.1)
            eng.on_text(ev)
            if ev.final:
                finals.append(ev.text)
        transcripts.append(f"{name}: {' | '.join(finals)}")
        errors += check_expectations(name, sc, eng.events)
    assert not errors, "\n".join(errors + ["", "Распознано:"] + transcripts)
