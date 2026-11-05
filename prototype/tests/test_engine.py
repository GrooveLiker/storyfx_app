from conftest import check_expectations, feed_text, make_engine


def test_scenarios_as_text_keywords_only(triggers, scene_data, scenarios, clock):
    """Все сценарии на «идеальном» распознавании (текст), сцены только по ключевым словам."""
    errors = []
    for name, sc in scenarios.items():
        eng = make_engine(sc["mode"], triggers, scene_data, clock)
        feed_text(eng, sc["text"], clock)
        errors += check_expectations(name, sc, eng.events)
    assert not errors, "\n".join(errors)


def test_audio_commands(triggers, scene_data, clock):
    eng = make_engine("dnd", triggers, scene_data, clock)
    feed_text(eng, "Начался дождь. Герои вошли в лес. Орк упал.", clock)
    log = eng.audio.log
    assert ("overlays", "rain") in log
    assert ("scene", "forest") in log
    assert ("sfx", "fall") in log
