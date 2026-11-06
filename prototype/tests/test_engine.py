from conftest import feed_text, make_engine


def test_audio_commands(actions, scene_data, clock):
    eng = make_engine(actions, scene_data, clock)
    feed_text(eng, "Начался дождь. Герои вошли в лес. Орк упал на землю.", clock)
    log = eng.audio.log
    assert ("overlays", "rain") in log
    assert ("scene", "forest") in log
    assert ("sfx", "fall") in log


def test_scenes_and_overlays_from_scenarios(actions, scene_data, scenarios, clock):
    """Сцены и наложения по ключевым словам — без модели смысла. Звуки действий — в test_e2e."""
    errors = []
    for name, sc in scenarios.items():
        eng = make_engine(actions, scene_data, clock)
        feed_text(eng, sc["text"], clock)
        for kind in ("scene", "overlay_on"):
            for i in (sc.get("expect") or {}).get(kind, []):
                if (kind, i) not in eng.events:
                    errors.append(f"{name}: нет {kind}={i}")
    assert not errors, "\n".join(errors)
