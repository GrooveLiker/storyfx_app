from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from storyfx.asr import TextEvent
from storyfx.audio import NullAudio
from storyfx.engine import StoryEngine
from storyfx.scenes import SceneTracker, load_scenes
from storyfx.actions import ActionMatcher, load_actions

TESTS = Path(__file__).parent


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture(scope="session")
def actions():
    return load_actions()


@pytest.fixture(scope="session")
def scene_data():
    return load_scenes()


@pytest.fixture(scope="session")
def mood_data():
    from storyfx.mood import load_moods
    return load_moods()


@pytest.fixture(scope="session")
def scenarios():
    return yaml.safe_load((TESTS / "scenarios.yaml").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def characters():
    from storyfx.characters import load_characters
    return load_characters()


def make_engine(actions, scene_data, clock, embedder=None, characters=None, mixer=False):
    from storyfx.characters import CharacterTracker
    from storyfx.mixer import SoundMixer
    scenes, overlays = scene_data
    return StoryEngine(
        actions=ActionMatcher(list(actions), embedder=embedder, clock=clock),
        scenes=SceneTracker(list(scenes), list(overlays), embedder=embedder),
        mixer=SoundMixer(clock=clock) if mixer else None,
        audio=NullAudio(),
        log=lambda m: None,
        clock=clock,
        characters=CharacterTracker(list(characters), clock=clock) if characters else None,
    )


def feed_text(engine, text: str, clock=None, step: float = 0.3):
    """Подаёт текст как распознавание: по предложениям, каждое — пословно частичными результатами."""
    import re
    for sent in [s for s in re.split(r"[.!?]+", text) if s.strip()]:
        words = sent.split()
        for i in range(1, len(words) + 1):
            engine.on_text(TextEvent(" ".join(words[:i]), False))
            if clock:
                clock.advance(step)
        engine.on_text(TextEvent(" ".join(words), True))
        if clock:
            clock.advance(1.0)


def check_expectations(name, sc, events):
    errors = []
    for kind, ids in (sc.get("expect") or {}).items():
        for i in ids:
            if (kind, i) not in events:
                errors.append(f"{name}: нет ожидаемого события {kind}={i}")
    for kind, ids in (sc.get("forbid") or {}).items():
        for i in ids:
            if (kind, i) in events:
                errors.append(f"{name}: запрещённое событие {kind}={i}")
    return errors
