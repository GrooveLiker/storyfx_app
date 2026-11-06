"""Звукооператор (D-010): напряжённость из настроения и темпа речи → громкость слоёв, плавно."""
from conftest import feed_text, make_engine

from storyfx import config
from storyfx.asr import TextEvent
from storyfx.mixer import SoundMixer
from storyfx.mood import make_mood_tracker


def speak(m: SoundMixer, clock, words: int, per_word: float):
    """Одна фраза: слова появляются по одному, как частичные результаты Vosk, затем финал."""
    for i in range(1, words + 1):
        clock.advance(per_word)
        m.on_words(i, final=False)
        m.update()
    m.on_words(words, final=True)


def test_starts_calm(clock):
    m = SoundMixer(clock=clock)
    assert m.intensity == config.MOOD_INTENSITY["calm"]
    amb, _, sfx, _ = m.levels()
    assert amb > 0.45 and sfx < 0.75                     # спокойно: слышно место, действия мягкие


def test_mood_moves_intensity_smoothly(clock):
    m = SoundMixer(clock=clock)
    m.update()
    m.mood = "action"
    clock.advance(1.0)
    one_sec = m.update()
    assert config.MOOD_INTENSITY["calm"] < one_sec < 0.5      # за секунду — только часть пути
    clock.advance(20)
    assert m.update() > 0.9                                   # дошло до «динамично»
    amb, _, sfx, music = m.levels()
    assert sfx > 0.95 and amb < 0.35 and music > config.MIX_CALM[3]


def test_tempo_unknown_with_few_words(clock):
    m = SoundMixer(clock=clock)
    speak(m, clock, 3, 0.1)
    assert m.tempo() is None and m.target() == config.MOOD_INTENSITY["calm"]


def test_fast_speech_raises_slow_speech_lowers(clock):
    fast, slow = SoundMixer(clock=clock, mood="cheerful"), None
    speak(fast, clock, 20, 0.2)                               # 5 сл/с — торопится
    assert fast.tempo() > config.TEMPO_FAST
    assert fast.target() > config.MOOD_INTENSITY["cheerful"]
    clock.advance(config.TEMPO_WINDOW_S + 1)
    slow = SoundMixer(clock=clock, mood="cheerful")
    speak(slow, clock, 12, 0.8)                               # 1,25 сл/с — неторопливо
    assert slow.tempo() < config.TEMPO_SLOW
    assert slow.target() < config.MOOD_INTENSITY["cheerful"]


def test_old_words_leave_window(clock):
    m = SoundMixer(clock=clock)
    speak(m, clock, 20, 0.2)
    clock.advance(config.TEMPO_WINDOW_S + 1)
    m.on_words(0, final=False)
    assert m.tempo() is None                                  # замолчал — темп забыт


def test_engine_mixes_by_story(actions, scene_data, mood_data, clock):
    moods, default = mood_data
    eng = make_engine(actions, scene_data, clock, mixer=True)
    eng.moods = make_mood_tracker(moods, default)
    eng.on_text(TextEvent("жили-были", False))
    calm_sfx = eng.audio.mix[2]
    feed_text(eng, "Вдруг за ними началась погоня. Бегите скорее, спасайтесь.", clock, step=0.2)
    for _ in range(10):                                       # рассказчик продолжает — микс догоняет
        clock.advance(1.0)
        eng.on_text(TextEvent("бегите", False))
    assert eng.mood == "action"
    assert eng.audio.mix[2] > calm_sfx + 0.2 and eng.mixer.intensity > 0.7
