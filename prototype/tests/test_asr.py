"""Конец фразы по паузе в звуке (задача 26) — без Vosk: громкость блоков подаём руками."""
from storyfx.asr import SilenceGate

DT = 0.1                 # блок звука, с
SPEECH, QUIET = 0.05, 0.0


def run(gate, levels):
    """Громкости блоков → номера блоков, на которых фраза кончилась."""
    return [i for i, rms in enumerate(levels) if gate.update(rms, DT)]


def test_long_pause_ends_phrase():
    gate = SilenceGate(pause=0.6, min_rms=0.004)
    ends = run(gate, [SPEECH] * 10 + [QUIET] * 8 + [SPEECH] * 5)
    assert ends == [15]                         # шестой тихий блок подряд — 0,6 с


def test_comma_pause_does_not_end():
    gate = SilenceGate(pause=0.6, min_rms=0.004)
    assert run(gate, [SPEECH] * 10 + [QUIET] * 3 + [SPEECH] * 10) == []     # запятая — 0,3 с


def test_silence_before_speech_is_not_a_phrase():
    gate = SilenceGate(pause=0.6, min_rms=0.004)
    assert run(gate, [QUIET] * 20) == []        # ещё ничего не сказали


def test_one_end_per_pause():
    gate = SilenceGate(pause=0.6, min_rms=0.004)
    assert run(gate, [SPEECH] * 5 + [QUIET] * 30) == [10]


def test_noisy_microphone():
    """Шум микрофона 0,01 — громче min_rms; за несколько секунд до рассказа порог подстроился под шум."""
    gate = SilenceGate(pause=0.6, min_rms=0.004)
    noise, speech = 0.01, 0.08
    ends = run(gate, [noise] * 50 + [speech] * 10 + [noise] * 8 + [speech] * 3)
    assert ends == [65]


def test_long_speech_does_not_raise_threshold_above_speech():
    """10 с речи без пауз (паузы между словами — тише): порог не дорастает до речи, ложных концов нет."""
    gate = SilenceGate(pause=0.6, min_rms=0.004)
    word = [0.06, 0.07, 0.05, 0.02]          # слово и провал между словами
    assert run(gate, [0.0] * 5 + word * 25) == []
