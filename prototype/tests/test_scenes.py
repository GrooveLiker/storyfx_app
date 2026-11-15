import numpy as np

from storyfx import config
from storyfx.scenes import SceneTracker


class KeywordishEmbedder:
    """Фейковая модель смысла: вектор = мешок из нескольких опорных слов. Хватает для проверки гистерезиса."""
    VOCAB = ["лес", "дерев", "птиц", "мор", "волн", "корабл", "таверн", "эль", "пещер", "темн"]

    def encode(self, texts):
        out = []
        for t in texts:
            v = np.array([t.lower().count(w) for w in self.VOCAB], dtype=float) + 0.01
            out.append(v / np.linalg.norm(v))
        return np.array(out)


def tracker(scene_data, embedder=None):
    scenes, overlays = scene_data
    return SceneTracker(list(scenes), list(overlays), embedder=embedder)


def kinds(changes):
    return [(c.kind, c.id) for c in changes]


def test_explicit_keyword_switches_immediately(scene_data):
    t = tracker(scene_data)
    assert ("scene", "forest") in kinds(t.add_utterance("отряд вошёл в густой лес"))
    assert ("scene", "tavern") in kinds(t.add_utterance("герои зашли в таверну"))
    assert t.current == "tavern"


def test_fairytale_scenes_by_keyword(scene_data):
    t = tracker(scene_data)
    assert ("scene", "village") in kinds(t.add_utterance("жили-были дед да баба в деревне"))
    assert ("scene", "home") in kinds(t.add_utterance("бабушка испекла пирожки в печи"))
    assert ("scene", "swamp") in kinds(t.add_utterance("стрела упала прямо в болото"))
    assert ("scene", "castle") in kinds(t.add_utterance("Иван пришёл во дворец"))   # «дворец» — не «двор»


def test_semantic_switch_needs_confirmation(scene_data):
    t = tracker(scene_data, embedder=KeywordishEmbedder())
    t.add_utterance("отряд вошёл в густой лес")
    t._words = "кругом шумели волны и качался корабль волны волны".split()
    t._since_switch = config.SCENE_MIN_DWELL                      # выдержка после смены прошла (её тест — ниже)
    tries = [t.evaluate() for _ in range(config.SCENE_CONFIRM)]
    assert all(c is None for c in tries[:-1]) and tries[-1] is not None and tries[-1].id == "sea"


def test_semantic_switch_ignores_short_text(scene_data):
    """2–3 слова («на опушке») — не смысл: по ним сцену не меняем (задача 23, шаг 4)."""
    t = tracker(scene_data, embedder=KeywordishEmbedder())
    t._words = "волны корабль".split()
    assert all(t.evaluate() is None for _ in range(5))


def test_semantic_switch_waits_after_change(scene_data):
    """Только что сменили сцену — несколько фраз по смыслу её не трогаем."""
    t = tracker(scene_data, embedder=KeywordishEmbedder())
    t.add_utterance("отряд вошёл в густой лес")                   # ключевое слово — сразу
    t._words = "кругом шумели волны и качался корабль волны волны".split()
    assert all(t.evaluate() is None for _ in range(5))            # фраз после смены ещё нет
    for _ in range(config.SCENE_MIN_DWELL):
        t._since_switch += 1
    assert any(t.evaluate() is not None for _ in range(config.SCENE_CONFIRM))


def test_overlay_on_and_off(scene_data):
    t = tracker(scene_data)
    assert ("overlay_on", "rain") in kinds(t.add_utterance("начался сильный дождь"))
    assert "rain" in t.active_overlays
    assert ("overlay_off", "rain") in kinds(t.add_utterance("наконец дождь закончился"))
    assert "rain" not in t.active_overlays


def test_comparison_is_not_weather_or_place(scene_data):
    """«Старуха как гроза разразилась» — сравнение (задача 23, шаг 5)."""
    t = tracker(scene_data)
    t.add_utterance("тут старуха как гроза разразилась")
    assert "storm" not in t.active_overlays
    t.add_utterance("глаза у неё как море")
    assert t.current != "sea"
    t.add_utterance("разразилась гроза")
    assert "storm" in t.active_overlays


def test_overlay_negated(scene_data):
    t = tracker(scene_data)
    t.add_utterance("дождя не было, ни ветерка")
    assert t.active_overlays == []
    t.add_utterance("снега нет")
    assert t.active_overlays == []


def test_max_overlays(scene_data):
    t = tracker(scene_data)
    t.add_utterance("пошёл дождь")
    t.add_utterance("подул сильный ветер")
    t.add_utterance("наступила ночь")
    assert len(t.active_overlays) == 2 and "rain" not in t.active_overlays


def test_battle_and_storm_always_available(scene_data):
    """Режимов больше нет (D-010): битва и гроза доступны всегда."""
    t = tracker(scene_data)
    t.add_utterance("началась битва")
    assert t.current == "battle"
    t.add_utterance("разразилась гроза")
    assert "storm" in t.active_overlays


# ---------- шаг 6 задачи 23: реплики героев не меняют место и погоду ----------
def _speech(text):
    from storyfx.textnorm import mark_speech, speech_words
    words, mask, _ = speech_words(mark_speech(text))
    return " ".join(words), tuple(mask)


def test_mark_speech_quotes_and_dash_lines():
    from storyfx.textnorm import mark_speech, speech_words
    words, mask, open_ = speech_words(mark_speech("Дед сказал: «Пойду в лес»"))
    assert [w for w, s in zip(words, mask) if s] == ["пойду", "в", "лес"]
    assert not open_
    # строка с тире: реплика — слова автора — снова реплика
    words, mask, _ = speech_words(mark_speech("— Иди в лес, — сказала баба, — за дровами."))
    spoken = [w for w, s in zip(words, mask) if s]
    assert "лес" in spoken and "дровами" in spoken and "сказала" not in spoken


def test_speech_words_carries_open_quote_to_next_phrase():
    from storyfx.textnorm import mark_speech, speech_words
    _, mask1, open_ = speech_words(mark_speech("«Ох, в лесу страшно!"))
    assert open_ and all(mask1)
    words, mask2, open_ = speech_words(mark_speech("Пойдём домой» — сказал он."), open_)
    assert mask2[:2] == [True, True] and not mask2[-1] and not open_


def test_place_in_speech_does_not_switch_scene(scene_data):
    t = tracker(scene_data)
    t.add_utterance("жили-были дед да баба в деревне")
    text, mask = _speech("Баба говорит: «Сходи в лес за дровами»")
    assert ("scene", "forest") not in kinds(t.add_utterance(text, speech=mask))
    assert t.current == "village"
    text, mask = _speech("Дед пошёл в лес")
    assert ("scene", "forest") in kinds(t.add_utterance(text, speech=mask))


def test_weather_in_speech_does_not_add_overlay(scene_data):
    t = tracker(scene_data)
    text, mask = _speech("Старик кричит: «Буря на море!»")
    assert ("overlay_on", "storm") not in kinds(t.add_utterance(text, speech=mask))
    text, mask = _speech("На море разыгралась буря")
    assert ("overlay_on", "storm") in kinds(t.add_utterance(text, speech=mask))
