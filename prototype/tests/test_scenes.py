import numpy as np

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
    first = t.evaluate()
    second = t.evaluate()
    assert first is None and second is not None and second.id == "sea"


def test_overlay_on_and_off(scene_data):
    t = tracker(scene_data)
    assert ("overlay_on", "rain") in kinds(t.add_utterance("начался сильный дождь"))
    assert "rain" in t.active_overlays
    assert ("overlay_off", "rain") in kinds(t.add_utterance("наконец дождь закончился"))
    assert "rain" not in t.active_overlays


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
