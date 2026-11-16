"""Реплики героев в речи без кавычек (голос): speech.py + data/speech.yaml."""
import pytest

from storyfx.scenes import tokenize_words
from storyfx.speech import load_speech_cues


@pytest.fixture(scope="module")
def cues():
    return load_speech_cues()


def spoken(cues, text):
    words = tokenize_words(text)
    return [w for w, m in zip(words, cues.guess(words)) if m]


def test_imperative_marks_following_words(cues):
    assert spoken(cues, "будь умна береги брата не ходи со двора") == ["береги", "брата", "не", "ходи", "со", "двора"]


def test_first_person_and_address(cues):
    assert "морскою" in spoken(cues, "не хочу быть вольною царицей хочу быть владычицей морскою")
    assert {"печка", "скажи"} <= set(spoken(cues, "стоит печка печка печка скажи куда гуси полетели"))


def test_narration_verb_ends_the_line(cues):
    """«…не едят тебя | побежала дальше, стоит молочная речка» — речка остаётся местом."""
    s = spoken(cues, "у моего батюшки и садовые не едят тебя побежала дальше стоит молочная речка")
    assert "тебя" in s and "побежала" not in s and "речка" not in s


def test_plain_narration_is_not_speech(cues):
    assert spoken(cues, "жил старик со своею старухой у самого синего моря") == []
    assert spoken(cues, "девочка выбежала в чистое поле и увидела гусей") == []


def test_engine_voice_speech_does_not_switch_scene(actions, scene_data, clock):
    """Голос (без разметки): реплика с местом не меняет сцену, рассказ — меняет. Текст с кавычками — как раньше."""
    from conftest import make_engine
    from storyfx.asr import TextEvent
    eng = make_engine(actions, scene_data, clock)
    eng.speech_cues = load_speech_cues()
    eng.on_text(TextEvent("жили были дед да баба в деревне", True))
    eng.on_text(TextEvent("баба говорит сходи в лес за дровами", True))
    assert ("scene", "forest") not in eng.events
    eng.on_text(TextEvent("дед пошёл в лес", True))
    assert ("scene", "forest") in eng.events
