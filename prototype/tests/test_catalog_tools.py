"""Каталог: «Не нужен» (выключить звук), «Свой файл» (загрузка), «Найти другие» (свои запросы к Freesound).
Без сети: Freesound подменён. Всё пишется во временную папку, настоящие sounds/ и data/ не трогаются."""
import json
import shutil
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path

import numpy as np
import pytest
import yaml

from conftest import feed_text, make_engine
from storyfx import muted as mt
from storyfx import soundproc as sp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import catalog as cat  # noqa: E402
import fetch_freesound as ff  # noqa: E402
import pick_sounds as ps  # noqa: E402

SR = sp.SR


def tone_wav(path: Path, seconds: float = 1.5) -> Path:
    t = np.arange(int(seconds * SR)) / SR
    sp.write_wav(path, np.sin(2 * np.pi * 330 * t) * np.exp(-t) * 0.8)
    return path


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    for mod in (ps, ff):
        monkeypatch.setattr(mod, "CANDIDATES", tmp_path / "sounds" / "candidates")
        monkeypatch.setattr(mod, "CHOSEN", tmp_path / "sounds" / "chosen.yaml")
        monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(ps, "LICENSES", tmp_path / "sounds" / "LICENSES.md")
    queries = tmp_path / "freesound_queries.yaml"
    shutil.copyfile(cat.QUERIES, queries)
    monkeypatch.setattr(cat, "QUERIES", queries)
    monkeypatch.setattr(ff, "QUERIES", queries)
    monkeypatch.setattr(mt, "MUTED_FILE", tmp_path / "muted.yaml")
    monkeypatch.setattr(cat, "JOBS", {})
    for kind in ("sfx", "ambience"):
        (tmp_path / "sounds" / kind).mkdir(parents=True)
    return tmp_path


def need_ffmpeg():
    if not shutil.which("ffmpeg"):
        pytest.skip("нет ffmpeg")


# ---------- «Не нужен» ----------
def test_mute_toggle(sandbox):
    assert cat.set_muted("sfx/owl", True)["muted"]
    assert mt.load_muted() == {"sfx/owl"}
    assert not cat.set_muted("sfx/owl", False)["muted"]
    assert mt.load_muted() == set()
    with pytest.raises(ValueError):
        cat.set_muted("sfx/../x", True)


def test_engine_respects_muted(actions, scene_data, characters, clock):
    eng = make_engine(actions, scene_data, clock, characters=characters)
    eng.muted = {"sfx/fall", "ambience/forest", "sfx/fox_yelp"}
    feed_text(eng, "Герои вошли в густой лес. Орк упал на землю. Навстречу вышла лиса.", clock)
    assert ("scene", "forest") in eng.events and ("sfx", "fall") in eng.events and ("char", "fox") in eng.events
    assert ("sfx", "fall") not in eng.audio.log and ("sfx", "fox_yelp") not in eng.audio.log   # но не звучат
    assert ("scene", None) in eng.audio.log and ("scene", "forest") not in eng.audio.log


# ---------- «Свой файл» ----------
def test_upload_own_sound(sandbox):
    need_ffmpeg()
    data = tone_wav(sandbox / "src.wav").read_bytes()
    it = cat.upload("sfx/owl", "моя сова.wav", data)
    assert it["own"] and it["reviewed"] and it["current"]["name"] == "моя сова.wav"
    assert (sandbox / "sounds" / "sfx" / "owl.wav").exists()
    assert (sandbox / "sounds" / "own" / "sfx__owl.wav").exists()           # копия для git
    chosen = yaml.safe_load((sandbox / "sounds" / "chosen.yaml").read_text(encoding="utf-8"))
    assert chosen["sfx/owl"]["license"] == ps.OWN_LICENSE
    lic = (sandbox / "sounds" / "LICENSES.md").read_text(encoding="utf-8")
    assert "своя запись: sounds/own/sfx__owl.wav" in lic and "CC0" not in lic.split("sfx/owl.wav")[1].split("\n")[0]


def test_upload_rejects_bad_files(sandbox):
    need_ffmpeg()
    with pytest.raises(ValueError):
        cat.upload("sfx/owl", "notes.txt", b"hello")
    with pytest.raises(ValueError):
        cat.upload("sfx/owl", "empty.wav", b"")
    with pytest.raises(ValueError):                                         # фон короче 10 с
        cat.upload("ambience/forest", "short.wav", tone_wav(sandbox / "s.wav", 3).read_bytes())


def test_own_sound_restored_on_new_machine(sandbox, monkeypatch):
    need_ffmpeg()
    cat.upload("sfx/owl", "моя сова.wav", tone_wav(sandbox / "src.wav").read_bytes())
    (sandbox / "sounds" / "sfx" / "owl.wav").unlink()                       # «новый компьютер»: wav не в git
    monkeypatch.setattr(ff.Freesound, "sound", lambda self, i: pytest.fail("своё не качаем с Freesound"))
    ff.fetch_chosen(ff.Freesound("k"))
    assert (sandbox / "sounds" / "sfx" / "owl.wav").exists()


# ---------- «Найти другие» ----------
@pytest.fixture
def fake_freesound(sandbox, monkeypatch):
    need_ffmpeg()
    mp3 = sandbox / "src.mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(tone_wav(sandbox / "t.wav")), str(mp3)], check=True)
    results = {"value": []}

    def result(i):
        return {"id": i, "name": f"owl {i}", "username": f"user{i}", "duration": 1.5, "num_downloads": 10,
                "avg_rating": 4, "license": "http://creativecommons.org/publicdomain/zero/1.0/",
                "url": f"https://freesound.org/s/{i}/", "previews": {"preview-hq-mp3": "x"}}

    monkeypatch.setattr(ff.Freesound, "get", lambda self, path, **p: {"results": [result(i) for i in results["value"]]})
    monkeypatch.setattr(ff, "download", lambda url, dst: shutil.copyfile(mp3, dst))
    monkeypatch.setattr(ff, "api_key", lambda: "k")
    return results


def test_search_replaces_candidates_and_saves_queries(sandbox, fake_freesound):
    fake_freesound["value"] = [11, 12, 13]
    it = cat.search("sfx/owl", ["owl hoot night", "tawny owl"], count=2, wait=True)
    assert it["job"]["state"] == "done" and [c["freesound_id"] for c in it["candidates"]] == [11, 12]
    q = yaml.safe_load(cat.QUERIES.read_text(encoding="utf-8"))
    assert q["sfx"]["owl"]["queries"] == ["owl hoot night", "tawny owl"]
    assert "# Поисковые запросы" in cat.QUERIES.read_text(encoding="utf-8")   # комментарии на месте


def test_failed_search_keeps_old_candidates(sandbox, fake_freesound):
    fake_freesound["value"] = [21]
    cat.search("sfx/owl", ["owl"], wait=True)
    fake_freesound["value"] = []
    it = cat.search("sfx/owl", ["zzzz nothing"], wait=True)
    assert it["job"]["state"] == "error" and [c["freesound_id"] for c in it["candidates"]] == [21]
    assert yaml.safe_load(cat.QUERIES.read_text(encoding="utf-8"))["sfx"]["owl"]["queries"] == ["owl"]


def test_search_without_key_reports_error(sandbox, monkeypatch):
    monkeypatch.setattr(ff, "api_key", lambda: sys.exit("Нет ключа Freesound."))
    it = cat.search("sfx/owl", ["owl"], wait=True)
    assert it["job"]["state"] == "error" and "ключ" in it["job"]["msg"]


def test_set_queries_rejects_unknown(sandbox):
    with pytest.raises(ValueError):
        ff.set_queries("sfx", "no_such_sound", ["x"], cat.QUERIES)


# ---------- HTTP ----------
def test_http_upload_and_mute(sandbox):
    need_ffmpeg()
    from live_session import LiveSession
    srv = cat.serve(0, session=LiveSession(engine_factory=lambda log: None, sleep=lambda _: None))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        body = tone_wav(sandbox / "u.wav").read_bytes()
        req = urllib.request.Request(base + "/api/upload?key=sfx%2Fowl&name=my.wav", data=body, method="POST")
        assert json.loads(urllib.request.urlopen(req).read())["own"]
        req = urllib.request.Request(base + "/api/mute", data=json.dumps({"key": "sfx/owl", "on": True}).encode(),
                                     method="POST", headers={"Content-Type": "application/json"})
        assert json.loads(urllib.request.urlopen(req).read())["muted"]
        got = json.loads(urllib.request.urlopen(base + "/api/item?key=sfx%2Fowl").read())
        assert got["muted"] and got["own"]
    finally:
        srv.shutdown()
