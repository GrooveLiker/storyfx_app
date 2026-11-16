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
    """Присутствие — по фразам, не по секундам (задача 23, шаг 5)."""
    assert ids(tracker, "пришёл медведь") == ["bear"]
    clock.advance(1000)                                               # долго печатали — неважно
    assert ids(tracker, "медведь рассердился") == []                  # уже здесь
    for _ in range(config.CHARACTER_REINTRO_PHRASES - 2):
        ids(tracker, "шёл дождь")
    assert ids(tracker, "медведь зарычал") == []                      # 28 фраз молчания — всё ещё здесь
    for _ in range(config.CHARACTER_REINTRO_PHRASES):
        ids(tracker, "шёл дождь")
    assert ids(tracker, "и снова явился медведь") == ["bear"]         # 30 фраз о нём ни слова — появился заново


def test_comparison_is_not_appearance(tracker):
    assert ids(tracker, "силён он был, как медведь") == []
    assert ids(tracker, "старуха визжала, словно лиса") == ["old_woman"]


def test_address_is_not_appearance(tracker):
    """«Что ты наделал, старый пёс?» — ругают старика, собаки нет."""
    assert ids(tracker, "что ты наделал, старый пёс") == []
    assert ids(tracker, "во двор вбежал пёс") == ["dog"]
    assert ids(tracker, "ну что ты лаешь, пёс") == []                  # пёс уже здесь — к нему обращаются


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
    eng._last_action_t = clock()       # как если бы только что прозвучал звук действия
    eng.on_text(TextEvent("пришёл медведь", True))
    assert ("char", "bear") not in eng.events
    clock.advance(config.CHARACTER_AFTER_ACTION_S + 0.1)
    eng.on_text(TextEvent("пришла лиса", True))   # звук действия был давно
    assert ("char", "fox") in eng.events


def test_character_voiced_in_long_phrase_after_early_action(actions, scene_data, characters, clock):
    """Голос: Vosk отдаёт фразу до паузы (бывает 30 слов). Звук действия в начале длинной фразы
    не глушит персонажа, названного через 10 секунд."""
    from storyfx.asr import TextEvent
    eng = make_engine(actions, scene_data, clock, characters=characters)
    eng._last_action_t = clock()
    clock.advance(10.0)
    eng.on_text(TextEvent("и тут на ёлке появился морозко", True))
    assert ("char", "frost") in eng.events


def test_voice_quiet_in_wrong_mood(actions, scene_data, characters, mood_data, clock):
    """Детский смех, когда мальчика уносят гуси, — не к месту: у ребёнка quiet_moods [tense, action]."""
    from storyfx.mood import make_mood_tracker
    eng = make_engine(actions, scene_data, clock, characters=characters)
    eng.moods = make_mood_tracker(*mood_data)
    eng.world.mood = "tense"
    feed_text(eng, "Налетели гуси и подхватили мальчика.", clock)
    assert ("char", "goose") in eng.events and ("char", "child") not in eng.events
    assert ("sfx", "child_laugh") not in eng.audio.log
    happy = make_engine(actions, scene_data, clock, characters=characters)   # новый рассказ: ребёнка ещё не было
    happy.moods = make_mood_tracker(*mood_data)
    happy.world.mood = "cheerful"
    feed_text(happy, "Во двор прибежала девочка.", clock)
    assert ("sfx", "child_laugh") in happy.audio.log                    # весело — смех к месту
