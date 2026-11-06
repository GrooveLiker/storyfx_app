"""Персонаж при появлении: распознавание имён, повторное появление, отрицания, движок."""
import pytest

from conftest import feed_text, make_engine
from storyfx import config
from storyfx.characters import CharacterTracker


def ids(tracker, text):
    return [a.character.id for a in tracker.process(text)]


@pytest.fixture
def tracker(characters, clock):
    return CharacterTracker(list(characters), clock=clock)


@pytest.mark.parametrize("text,expected", [
    ("жили-были дед да баба", ["old_man", "old_woman"]),
    ("вдруг выскочил серый волк", ["wolf"]),
    ("пришёл Дед Мороз", ["frost"]),                         # длинное имя важнее «деда»
    ("прилетела Баба-яга в ступе", ["witch"]),               # не бабушка
    ("Соловей-разбойник засвистел", ["nightingale"]),       # не разбойник
    ("Иван поймал жар-птицу", ["magic"]),                    # не просто птица
    ("Змей Горыныч прилетел", ["dragon"]),
    ("у пса была будка", ["dog"]),
    ("ёжик шёл в тумане", ["hedgehog"]),
    ("Машенька заблудилась", ["child"]),
    ("козлята заперли дверь", ["goat"]),
    ("бабка-ёжка костяная ножка", ["witch"]),
    # ложные совпадения
    ("дед курил трубку", ["old_man"]),                       # «курил» — не курица
    ("густой лес шумел", []),                                # не гуси
    ("совсем стемнело", []),                                 # не сова
    ("путник ослабел", []),                                  # не осёл
    ("это был конец пути", []),                              # не конь
    ("бабушка собирала ягоды", ["old_woman"]),               # «ягоды» — не Яга
    ("конь вороной", ["horse"]),                             # масть, не ворона
    ("пришла змея", []),                                     # «змея» — не Змей Горыныч (и звука змеи по «змее» нет)
])
def test_names(tracker, text, expected):
    assert ids(tracker, text) == expected


def test_negation_is_not_appearance(tracker):
    assert ids(tracker, "медведя в лесу не было") == []
    assert ids(tracker, "волка нигде нет") == []
    assert ids(tracker, "лиса в норе не спала") == ["fox"]      # «не» у другого слова — лиса есть
    assert ids(tracker, "тут пришёл медведь") == ["bear"]


def test_sound_once_then_again_after_silence(tracker, clock):
    assert ids(tracker, "пришёл медведь") == ["bear"]
    clock.advance(30)
    assert ids(tracker, "медведь рассердился") == []                  # уже здесь
    clock.advance(config.CHARACTER_REINTRO_S - 10)
    assert ids(tracker, "медведь ушёл") == []                         # упоминание продлило «присутствие»
    clock.advance(config.CHARACTER_REINTRO_S + 1)
    assert ids(tracker, "и снова явился медведь") == ["bear"]         # давно не было — появился заново


def test_max_per_phrase(tracker):
    got = ids(tracker, "пришли волк лиса заяц и медведь")
    assert got == ["wolf", "fox"] and len(got) == config.MAX_CHARACTERS_PER_PHRASE


def test_villains_have_voices(tracker):
    """Режимов больше нет (D-010): злодеи звучат всегда."""
    assert ids(tracker, "прилетел Змей Горыныч") == ["dragon"]
    assert ids(tracker, "злой Кощей Бессмертный") == ["villain"]


def test_engine_plays_character_sound(actions, scene_data, characters, clock):
    eng = make_engine(actions, scene_data, clock, characters=characters)
    feed_text(eng, "Жили-были дед да баба.", clock)
    assert ("char", "old_man") in eng.events and ("char", "old_woman") in eng.events
    assert ("sfx", "old_man_grunt") in eng.audio.log and ("sfx", "old_woman_sigh") in eng.audio.log


def test_engine_skips_character_if_action_sounded(actions, scene_data, characters, clock):
    from storyfx.asr import TextEvent
    eng = make_engine(actions, scene_data, clock, characters=characters)
    eng._action_in_utt = True          # как если бы в этой фразе уже прозвучал звук действия
    eng.on_text(TextEvent("пришёл медведь", True))
    assert ("char", "bear") not in eng.events
    eng.on_text(TextEvent("пришла лиса", True))   # следующая фраза — уже без звука действия
    assert ("char", "fox") in eng.events
