"""Подготовка звуков и конвейер Freesound без сети (API и скачивание подменены)."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import yaml

from storyfx import soundproc as sp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
SR = sp.SR
rng = np.random.default_rng(0)


def test_trim_silence():
    x = np.concatenate([np.zeros(SR), rng.standard_normal(SR // 2) * 0.3, np.zeros(SR)])
    y = sp.trim_silence(x)
    assert 0.5 * SR <= len(y) <= 0.55 * SR


def test_process_sfx_cut_and_level():
    x = np.concatenate([np.zeros(SR // 2), rng.standard_normal(5 * SR) * 0.05])
    y = sp.process_sfx(x, cut=2.0)
    assert len(y) <= 2.0 * SR
    assert np.max(np.abs(y)) <= sp.SFX_LEVEL[1] + 1e-6
    assert abs(y[-1]) < 1e-3 and abs(y[0]) < 1e-2          # плавные края, без щелчка


def test_process_ambience_loop():
    t = np.arange(60 * SR) / SR
    x = (np.sin(2 * np.pi * 220 * t) * (0.5 + 0.5 * np.sin(2 * np.pi * 0.1 * t))).astype(np.float32)
    y = sp.process_ambience(x, cut=20)
    assert 19 * SR <= len(y) <= 21 * SR
    assert abs(y[-1] - y[0]) < 0.05                          # стык петли непрерывный


def test_level_lifts_peaky_sound():
    """Треск костра: редкие резкие щелчки на тихом фоне — громкость поднимается, пики не выше потолка."""
    rng = np.random.default_rng(1)
    x = rng.standard_normal(44100 * 12) * 0.002
    x[rng.integers(0, len(x), 20)] = 0.9
    y = sp._level(x, *sp.AMB_LEVEL)
    rms = float(np.sqrt(np.mean(y ** 2)))
    by_peak = float(np.sqrt(np.mean((x * sp.AMB_LEVEL[1] / 0.9) ** 2)))   # старое поведение: пик упёрся в потолок
    assert np.max(np.abs(y)) <= sp.AMB_LEVEL[1] + 1e-6
    assert rms > 1.5 * by_peak


def test_ambience_too_short():
    with pytest.raises(ValueError):
        sp.process_ambience(np.zeros(5 * SR), cut=20)


@pytest.fixture
def fake_mp3(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("нет ffmpeg")
    wav = tmp_path / "src.wav"
    t = np.arange(int(1.5 * SR)) / SR
    sp.write_wav(wav, np.sin(2 * np.pi * 440 * t) * np.exp(-t * 2) * 0.8)
    mp3 = tmp_path / "src.mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(wav), str(mp3)], check=True)
    return mp3


def test_decode_mp3(fake_mp3):
    x = sp.decode(fake_mp3)
    assert abs(len(x) / SR - 1.5) < 0.1 and np.max(np.abs(x)) > 0.5


def test_fetch_and_pick_pipeline(tmp_path, fake_mp3, monkeypatch):
    import fetch_freesound as ff
    import pick_sounds as ps

    for mod in (ff, ps):
        monkeypatch.setattr(mod, "CANDIDATES", tmp_path / "candidates")
        monkeypatch.setattr(mod, "CHOSEN", tmp_path / "chosen.yaml")
    monkeypatch.setattr(ps, "LICENSES", tmp_path / "LICENSES.md")
    monkeypatch.setattr(ps, "ROOT", tmp_path)
    (tmp_path / "sounds" / "sfx").mkdir(parents=True)

    def result(i, lic, downloads):
        return {"id": i, "name": f"bell {i}", "username": f"user{i}", "license": lic, "duration": 1.5,
                "url": f"https://freesound.org/s/{i}/", "num_downloads": downloads, "avg_rating": 4,
                "previews": {"preview-hq-mp3": f"https://cdn.example/{i}.mp3"}}

    cc0 = "http://creativecommons.org/publicdomain/zero/1.0/"
    by = "https://creativecommons.org/licenses/by/4.0/"
    fake = [result(1, cc0, 10), result(2, by, 99999), result(3, cc0, 500)]
    monkeypatch.setattr(ff.Freesound, "get", lambda self, path, **p: {"results": fake})
    monkeypatch.setattr(ff, "download", lambda url, dst: shutil.copyfile(fake_mp3, dst))

    got = ff.fetch_candidates(ff.Freesound("k"), "sfx", "bell", {"queries": ["bell"], "min": 0, "max": 9, "cut": 1.0}, 5)
    meta = json.loads((tmp_path / "candidates/sfx/bell/meta.json").read_text(encoding="utf-8"))
    assert got == 2
    assert [m["id"] for m in meta] == [3, 1]                 # не-CC0 отброшен, популярный выше

    monkeypatch.setattr(sys, "argv", ["pick", "--auto"])
    ps.main()
    chosen = yaml.safe_load((tmp_path / "chosen.yaml").read_text(encoding="utf-8"))
    assert chosen["sfx/bell"]["id"] == 3
    assert (tmp_path / "sounds" / "sfx" / "bell.wav").exists()
    assert "freesound.org/s/3" in (tmp_path / "LICENSES.md").read_text(encoding="utf-8")
