"""«Тест озвучки» в каталоге: текст и «микрофон» через настоящий движок (без звука и без модели смысла)."""
import json
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from storyfx.asr import TextEvent
from storyfx.audio import NullAudio
from storyfx.cli import build_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import catalog as cat  # noqa: E402
from live_session import LiveSession, split_phrases  # noqa: E402


def quiet_engine(log):
    return build_engine(NullAudio(), use_embedder=False, log=log, music=True)


def wait(cond, timeout=5.0):
    t0 = time.monotonic()
    while not cond():
        if time.monotonic() - t0 > timeout:
            raise AssertionError("не дождались")
        time.sleep(0.01)


@pytest.fixture
def session():
    s = LiveSession(engine_factory=quiet_engine, sleep=lambda _: None)
    s.ensure_engine(wait=True)
    return s


def test_split_phrases():
    assert split_phrases("Жили-были дед да баба. Вдруг!\nПришёл волк…  ") == ["Жили-были дед да баба", "Вдруг", "Пришёл волк"]
    assert split_phrases("  ...  ") == []


def test_text_drives_engine(session):
    assert session.say("Герои вошли в густой лес. Начался сильный дождь. Навстречу вышла лиса.") == 3
    wait(lambda: not session.state()["busy"])
    st = session.state()
    assert st["status"] == "ready" and st["scene"] == "forest" and "rain" in st["overlays"]
    events = session.engine.events
    assert ("char", "fox") in events
    assert any("ПЕРСОНАЖ fox" in l["text"] for l in st["lines"])


def test_state_lines_since(session):
    last = session.state()["last"]
    session.say("Пошёл снег.")
    wait(lambda: not session.state()["busy"])
    new = session.state(since=last)["lines"]
    assert new and all(l["n"] > last for l in new)


def test_stop_resets_story(session):
    session.say("Герои вошли в таверну. Вдруг стало страшно.")
    wait(lambda: not session.state()["busy"])
    session.stop()
    st = session.state()
    assert st["scene"] is None and st["overlays"] == [] and st["mood"] == "calm"
    assert session.engine.audio.log[-1] == ("music", None)                 # тишина
    session.say("Навстречу вышла лиса.")                                 # персонаж снова «появляется»
    wait(lambda: not session.state()["busy"])
    assert session.engine.events.count(("char", "fox")) == 1


def test_music_toggle(session):
    session.set_music(False)
    assert not session.state()["music_on"]
    session.set_music(True)
    assert session.state()["music_on"]


def test_mic_with_fake_microphone(session):
    def fake_mic(device=None, stop=None):
        yield TextEvent("пошёл", False)
        yield TextEvent("пошёл дождь", True)
        while not stop.is_set():
            time.sleep(0.01)

    session._mic_factory = fake_mic
    session.mic_start()
    wait(lambda: "rain" in session.state()["overlays"])
    assert session.state()["listening"]
    session.mic_stop()
    wait(lambda: not session.state()["listening"])


def test_engine_error_is_reported():
    def broken(log):
        raise FileNotFoundError("нет модели Vosk")
    s = LiveSession(engine_factory=broken, sleep=lambda _: None)
    s.ensure_engine(wait=True)
    st = s.state()
    assert st["status"] == "error" and "Vosk" in st["error"]
    assert s.say("Пошёл дождь.") == 1                                       # не падает


def test_http_live_endpoints():
    s = LiveSession(engine_factory=quiet_engine, sleep=lambda _: None)
    srv = cat.serve(0, session=s)
    import threading
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def post(path, body):
        req = urllib.request.Request(base + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        return json.loads(urllib.request.urlopen(req).read())

    try:
        post("/api/live/start", {})
        assert post("/api/live/say", {"text": "Герои спустились в тёмную пещеру.", "tempo": "fast"})["phrases"] == 1
        wait(lambda: json.loads(urllib.request.urlopen(base + "/api/live/state").read())["scene"] == "cave")
        assert post("/api/live/stop", {})["scene"] is None
        assert json.loads(urllib.request.urlopen(base + "/api/live/state?since=abc").read())["status"] == "ready"
    finally:
        srv.shutdown()
