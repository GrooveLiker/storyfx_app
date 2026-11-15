"""«Тест озвучки» в каталоге: рассказчик пишет в поле или диктует — настоящий движок (без звука и модели смысла)."""
import json
import threading
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
from live_session import LiveSession, as_heard  # noqa: E402


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


def type_story(s: LiveSession, text: str):
    """Как страница: по мере письма — дописанные слова фразы, на точке — закрытая фраза."""
    for phrase in [p for p in text.split(".") if p.strip()]:
        words = phrase.split()
        for i in range(1, len(words)):
            s.feed_text(" ".join(words[:i]), final=False)
        s.feed_text(phrase + ".", final=True)


def test_as_heard_like_vosk():
    assert as_heard("Жили-были, дед да Баба!") == "жили-были дед да баба"
    assert as_heard("  — … ") == ""


def test_text_before_engine_ready_is_refused():
    s = LiveSession(engine_factory=quiet_engine, sleep=lambda _: None)
    with pytest.raises(ValueError):
        s.feed_text("пошёл дождь", final=True)


def test_typed_story_builds_world(session):
    type_story(session, "Герои вошли в густой лес. Начался сильный дождь. Навстречу вышла лиса.")
    st = session.state()
    assert st["status"] == "ready" and st["scene"] == "forest" and "rain" in st["overlays"]
    assert st["on_stage"] == ["Лиса"]                                         # из модели мира, именем для людей
    assert ("char", "fox") in session.engine.events
    assert any("ПЕРСОНАЖ fox" in l["text"] for l in st["lines"])


def test_partial_words_are_heard_before_the_dot(session):
    session.feed_text("вдалеке завыл", final=False)
    assert session.state()["partial"] == "вдалеке завыл"
    session.feed_text("вдалеке завыл волк.", final=True)
    assert session.state()["partial"] == ""


def test_punctuation_only_is_ignored(session):
    n = session.engine._utt
    assert session.feed_text("...", final=True) is False
    assert session.engine._utt == n                                           # фраза не закрылась


def test_state_lines_since(session):
    last = session.state()["last"]
    type_story(session, "Пошёл снег.")
    new = session.state(since=last)["lines"]
    assert new and all(l["n"] > last for l in new)


def test_stop_resets_story(session):
    type_story(session, "Герои вошли в таверну. Вдруг стало страшно.")
    session.stop()
    st = session.state()
    assert st["scene"] is None and st["overlays"] == [] and st["mood"] == "calm" and st["on_stage"] == []
    assert session.engine.audio.log[-1] == ("music", None)                   # тишина
    type_story(session, "Навстречу вышла лиса.")                             # персонаж снова «появляется»
    assert session.engine.events.count(("char", "fox")) == 1


def test_music_toggle(session):
    session.set_music(False)
    assert not session.state()["music_on"]
    session.set_music(True)
    assert session.state()["music_on"]


def test_dictation_phrases_go_to_the_text_field(session):
    def fake_mic(device=None, stop=None):
        yield TextEvent("пошёл", False)
        yield TextEvent("пошёл дождь", True)
        while not stop.is_set():
            time.sleep(0.01)

    session._mic_factory = fake_mic
    last = session.state()["last"]
    session.mic_start()
    wait(lambda: "rain" in session.state()["overlays"])
    st = session.state(since=last)
    assert st["listening"] and [h["text"] for h in st["heard"]] == ["пошёл дождь"]
    assert session.state(since=st["last"])["heard"] == []                     # не повторяется
    session.mic_stop()
    wait(lambda: not session.state()["listening"])


def test_engine_error_is_reported():
    def broken(log):
        raise FileNotFoundError("нет модели Vosk")
    s = LiveSession(engine_factory=broken, sleep=lambda _: None)
    s.ensure_engine(wait=True)
    st = s.state()
    assert st["status"] == "error" and "Vosk" in st["error"]
    with pytest.raises(ValueError):
        s.feed_text("пошёл дождь", final=True)


def test_http_live_endpoints():
    s = LiveSession(engine_factory=quiet_engine, sleep=lambda _: None)
    srv = cat.serve(0, session=s)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def post(path, body):
        req = urllib.request.Request(base + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        return json.loads(urllib.request.urlopen(req).read())

    try:
        post("/api/live/start", {})
        wait(lambda: s.status == "ready")
        assert post("/api/live/text", {"text": "Герои спустились", "final": False})["sent"]
        assert post("/api/live/text", {"text": "Герои спустились в тёмную пещеру.", "final": True})["sent"]
        assert json.loads(urllib.request.urlopen(base + "/api/live/state").read())["scene"] == "cave"
        assert post("/api/live/stop", {})["scene"] is None
        st = json.loads(urllib.request.urlopen(base + "/api/live/state?since=abc").read())
        assert st["status"] == "ready" and st["stale"] is False
    finally:
        srv.shutdown()


def test_stale_code_is_reported(monkeypatch):
    """Код обновили после запуска каталога — страница должна попросить перезапуск."""
    assert cat.code_is_stale() is False
    monkeypatch.setattr(cat, "STARTED_CODE", cat.STARTED_CODE - 3600)
    assert cat.code_is_stale() is True


def test_typing_and_speech_have_different_rhythm(session):
    """Набор: действия по смыслу, не по секундомеру; темп набора не учитывается. Речь: наоборот."""
    session.feed_text("пошёл", final=False)
    assert session.engine.actions.use_deadlines is False and session.engine.mixer.use_tempo is False

    def fake_mic(device=None, stop=None):
        yield TextEvent("гром", False)
        while not stop.is_set():
            time.sleep(0.01)

    session._mic_factory = fake_mic
    session.mic_start()
    wait(lambda: session.engine.actions.use_deadlines is True)
    assert session.engine.mixer.use_tempo is True
    session.mic_stop()
    wait(lambda: not session.state()["listening"])
