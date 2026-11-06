"""Целостность данных: каждый id из YAML имеет звук, звуки не битые."""
import wave

import numpy as np

from storyfx import config


def _wav(path):
    with wave.open(str(path), "rb") as w:
        assert w.getsampwidth() == 2, path
        x = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(float) / 32768
        return x, w.getframerate()


def test_every_action_has_sound(actions):
    missing = [s for g in actions for s in g.sounds if not (config.SOUNDS_DIR / "sfx" / f"{s}.wav").exists()]
    assert not missing, f"нет sounds/sfx для: {missing}"


def test_actions_have_enough_examples(actions):
    few = [f"{g.id}.{v.id}" for g in actions for v in g.variants if len(v.examples) < 2]
    assert not few, f"меньше 2 примеров: {few}"


def test_every_character_has_title(characters):
    untitled = [c.id for c in characters if c.title == c.id]
    assert not untitled, f"нет title (имени для людей) в characters.yaml: {untitled}"


def test_every_character_has_sound(characters):
    missing = [f"{c.id}:{c.sound}" for c in characters if not (config.SOUNDS_DIR / "sfx" / f"{c.sound}.wav").exists()]
    assert not missing, f"нет sounds/sfx для персонажей: {missing}"


def test_every_sound_is_used(actions, characters):
    used = {s for g in actions for s in g.sounds} | {c.sound for c in characters}
    unused = [p.stem for p in (config.SOUNDS_DIR / "sfx").glob("*.wav") if p.stem not in used]
    assert not unused, f"звуки не используются ни темой действия, ни персонажем: {unused}"


def test_every_sfx_has_freesound_query(actions, characters):
    import yaml
    q = yaml.safe_load((config.DATA_DIR / "freesound_queries.yaml").read_text(encoding="utf-8"))
    used = {s for g in actions for s in g.sounds} | {c.sound for c in characters}
    missing = sorted(used - set(q["sfx"]))
    assert not missing, f"нет запросов Freesound для: {missing}"


def test_every_scene_has_sound(scene_data):
    scenes, overlays = scene_data
    names = [s.ambience for s in scenes] + [o.ambience for o in overlays]
    missing = [n for n in names if not (config.SOUNDS_DIR / "ambience" / f"{n}.wav").exists()]
    assert not missing, f"нет sounds/ambience для: {missing}"


def test_sounds_are_sane():
    for path in sorted(config.SOUNDS_DIR.glob("*/*.wav")):
        x, sr = _wav(path)
        rms = float(np.sqrt(np.mean(x ** 2)))
        assert sr == 44100, path
        assert np.all(np.isfinite(x)), path
        assert rms > 0.01, f"{path.name}: почти тишина (rms={rms:.4f})"
        if path.parent.name == "ambience":
            assert len(x) / sr >= 8, f"{path.name}: фон короче 8 с"


def test_every_mood_has_music(mood_data):
    moods, default = mood_data
    assert {m.id for m in moods} == {"calm", "cheerful", "tense", "action"} and default == "calm"
    missing = [m.ambience for m in moods        # у настроения поле ambience = имя файла музыки
               if not (config.SOUNDS_DIR / "music" / f"{m.ambience}.wav").exists()]
    assert not missing, f"нет sounds/music для: {missing} — запустите tools/gen_music.py"


def test_ambience_loops_without_click():
    loops = sorted((config.SOUNDS_DIR / "ambience").glob("*.wav")) + sorted((config.SOUNDS_DIR / "music").glob("*.wav"))
    for path in loops:
        x, _ = _wav(path)
        jump = abs(x[-1] - x[0])
        typical = float(np.median(np.abs(np.diff(x)))) * 20 + 0.02
        assert jump < typical, f"{path.name}: щелчок на стыке петли ({jump:.3f})"
