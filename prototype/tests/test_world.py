"""Модель мира (D-011): кто на сцене, вход и уход персонажей, место не «откатывается», снимок для интерфейса."""
from conftest import feed_text, make_engine

from storyfx import config
from storyfx.characters import CharacterTracker
from storyfx.world import WorldState


def kinds(changes):
    return [(c.kind, c.id) for c in changes]


def observe(tracker, world, text):
    return kinds(world.observe_characters(tracker.observe(text)))


def test_enter_stay_leave_return(characters, clock):
    w = WorldState(clock=clock)
    t = CharacterTracker(list(characters), clock=clock)
    assert observe(t, w, "навстречу вышел заяц") == [("enter", "hare")]
    clock.advance(5)
    assert observe(t, w, "заяц испугался") == []                      # уже на сцене
    assert w.on_stage() == ["hare"]
    assert observe(t, w, "заяц испугался и убежал в лес") == [("leave", "hare")]
    assert w.on_stage() == []
    clock.advance(5)                                                  # через 10 с, не через 90
    assert observe(t, w, "потом снова прибежал заяц") == [("enter", "hare")]   # «прибежал» — не уход


def test_leaving_unknown_character_is_silent(characters, clock):
    w = WorldState(clock=clock)
    t = CharacterTracker(list(characters), clock=clock)
    assert observe(t, w, "где-то далеко волк убежал") == []           # не был на сцене — ни входа, ни ухода


def test_leave_only_in_its_clause(characters, clock):
    w = WorldState(clock=clock)
    t = CharacterTracker(list(characters), clock=clock)
    observe(t, w, "пришли заяц и лиса")
    assert observe(t, w, "заяц ускакал, а лиса осталась на поляне") == [("leave", "hare")]
    assert w.on_stage() == ["fox"]


def test_long_silence_counts_as_gone(characters, clock):
    w = WorldState(clock=clock)
    t = CharacterTracker(list(characters), clock=clock)
    observe(t, w, "пришёл медведь")
    for _ in range(config.CHARACTER_REINTRO_PHRASES):
        observe(t, w, "тихо шумел лес")
    assert w.on_stage() == []
    assert observe(t, w, "и снова медведь") == [("enter", "bear")]


def test_object_of_preposition_does_not_leave(characters, clock):
    """«Я у дедушки ушёл, я у бабушки ушёл» — ушёл колобок, дед и баба остались."""
    w = WorldState(clock=clock)
    t = CharacterTracker(list(characters), clock=clock)
    observe(t, w, "жили-были дед да баба")
    assert observe(t, w, "я у дедушки ушёл, я у бабушки ушёл") == []
    assert set(w.on_stage()) == {"old_man", "old_woman"}
    assert observe(t, w, "дед ушёл в лес") == [("leave", "old_man")]       # а тут дед — подлежащее


def test_max_entries_per_phrase(characters, clock):
    w = WorldState(clock=clock)
    t = CharacterTracker(list(characters), clock=clock)
    got = observe(t, w, "пришли волк лиса заяц и медведь")
    assert got == [("enter", "wolf"), ("enter", "fox")]


def test_place_weather_mood_and_snapshot(clock):
    w = WorldState(clock=clock)
    assert kinds(w.set_place("forest")) == [("place", "forest")]
    assert w.set_place("forest") == []                                # то же место — не изменение
    assert kinds(w.set_weather(["rain"], [("rain", True, "")])) == [("weather_on", "rain")]
    assert kinds(w.set_mood("tense")) == [("mood", "tense")]
    assert w.snapshot() == {"place": "forest", "weather": ["rain"], "mood": "tense", "on_stage": []}
    assert len(w.history) == 3
    w.reset()
    assert w.snapshot() == {"place": None, "weather": [], "mood": None, "on_stage": []}


def test_scene_window_forgets_old_place(scene_data):
    from storyfx.scenes import SceneTracker
    scenes, overlays = scene_data
    t = SceneTracker(list(scenes), list(overlays))
    t.add_utterance("жили-были дед да баба в деревне и было у них хозяйство большое")
    t.add_utterance("покатился колобок по дорожке прямо в лес")
    assert t.current == "forest"
    assert "деревне" not in t._words and len(t._words) <= config.SCENE_KEEP_AFTER_SWITCH


def test_scene_window_short_phrases(scene_data):
    """Короткие фразы: «…в деревне. Покатился колобок в лес.» — от деревни в окне ничего не осталось."""
    from storyfx.scenes import SceneTracker
    scenes, overlays = scene_data
    t = SceneTracker(list(scenes), list(overlays))
    t.add_utterance("жили-были дед да баба в деревне")
    t.add_utterance("покатился колобок в лес")
    assert t.current == "forest" and t._words == ["покатился", "колобок", "в", "лес"]


def test_engine_world_story(actions, scene_data, characters, clock):
    eng = make_engine(actions, scene_data, clock, characters=characters)
    feed_text(eng, "Жили-были дед да баба в деревне. Навстречу вышла лиса. Лиса испугалась и убежала. "
                   "Но скоро лиса вернулась.", clock)
    assert eng.events.count(("char", "fox")) == 2 and ("leave", "fox") in eng.events
    snap = eng.world.snapshot()
    assert snap["place"] == "village" and set(snap["on_stage"]) == {"old_man", "old_woman", "fox"}
