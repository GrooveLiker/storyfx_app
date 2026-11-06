"""Каталог звуков (tools/catalog.py): данные, выбор, отметка «оставить», безопасная раздача файлов, HTTP."""
import json
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
import pytest
import yaml

from storyfx import soundproc as sp

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import catalog as cat  # noqa: E402
import pick_sounds as ps  # noqa: E402


def test_catalog_lists_every_sound_with_usage():
    q = yaml.safe_load(cat.QUERIES.read_text(encoding="utf-8"))
    items = cat.catalog()
    assert len(items) == len(q["sfx"]) + len(q["ambience"])
    assert len({i["key"] for i in items}) == len(items)
    unused = [i["key"] for i in items if not i["used_by"]]
    assert not unused, f"звук ни к чему не привязан: {unused}"
    bear = next(i for i in items if i["key"] == "sfx/bear_growl")
    assert "персонаж: Медведь" in bear["used_by"]


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Свои папки вместо настоящих sounds/: кандидат для sfx/owl."""
    monkeypatch.setattr(ps, "ROOT", tmp_path)
    monkeypatch.setattr(ps, "CANDIDATES", tmp_path / "sounds" / "candidates")
    monkeypatch.setattr(ps, "CHOSEN", tmp_path / "sounds" / "chosen.yaml")
    monkeypatch.setattr(ps, "LICENSES", tmp_path / "sounds" / "LICENSES.md")
    folder = tmp_path / "sounds" / "candidates" / "sfx" / "owl"
    folder.mkdir(parents=True)
    (tmp_path / "sounds" / "sfx").mkdir(parents=True)
    t = np.arange(44100) / 44100
    sp.write_wav(folder / "1_42.wav", np.sin(2 * np.pi * 600 * t) * 0.5)
    (folder / "meta.json").write_text(json.dumps([{
        "n": 1, "file": "1_42.wav", "query": "owl", "id": 42, "name": "Owl hoot", "username": "someone",
        "license": "http://creativecommons.org/publicdomain/zero/1.0/", "duration": 1.0,
        "url": "https://freesound.org/s/42/"}]), encoding="utf-8")
    return tmp_path


def test_pick_installs_and_marks_reviewed(sandbox):
    item = cat.pick("sfx/owl", 1)
    assert item["current"]["freesound_id"] == 42 and item["reviewed"]
    assert item["candidates"][0]["current"]
    assert (sandbox / "sounds" / "sfx" / "owl.wav").exists()
    assert "sfx/owl" in yaml.safe_load((sandbox / "sounds" / "chosen.yaml").read_text(encoding="utf-8"))
    assert "freesound.org/s/42" in (sandbox / "sounds" / "LICENSES.md").read_text(encoding="utf-8")


def test_review_toggle(sandbox):
    assert cat.mark("sfx/owl", True)["reviewed"]
    assert yaml.safe_load(cat.reviewed_path().read_text(encoding="utf-8")) == {"sfx/owl": True}
    assert not cat.mark("sfx/owl", False)["reviewed"]


def test_bad_requests(sandbox):
    with pytest.raises(ValueError):
        cat.pick("sfx/owl", 9)
    with pytest.raises(ValueError):
        cat.pick("sfx/../../evil", 1)
    with pytest.raises(ValueError):
        cat.mark("music/calm", True)


def test_audio_path_stays_inside(sandbox):
    assert cat.audio_path("/audio/cand/sfx/owl/1_42.wav") is not None
    for bad in ["/audio/cand/sfx/owl/..%2F..%2F..%2Fchosen.yaml", "/audio/current/sfx/..%2Fchosen.yaml",
                "/audio/cand/sfx/owl/meta.json", "/audio/current/music/calm.wav", "/audio/x"]:
        assert cat.audio_path(bad) is None, bad


def test_http_server(sandbox):
    srv = cat.serve(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        assert srv.server_address[0] == "127.0.0.1"                       # только этот компьютер
        html = urllib.request.urlopen(base + "/").read().decode("utf-8")
        assert "Каталог звуков" in html
        sounds = json.loads(urllib.request.urlopen(base + "/api/sounds").read())
        assert any(s["key"] == "sfx/owl" for s in sounds)
        wav = urllib.request.urlopen(base + "/audio/cand/sfx/owl/1_42.wav").read()
        assert wav[:4] == b"RIFF"
        req = urllib.request.Request(base + "/api/pick", data=json.dumps({"key": "sfx/owl", "n": 1}).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        assert json.loads(urllib.request.urlopen(req).read())["reviewed"]
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(base + "/audio/current/sfx/..%2F..%2Fchosen.yaml")
        assert e.value.code == 404
    finally:
        srv.shutdown()
