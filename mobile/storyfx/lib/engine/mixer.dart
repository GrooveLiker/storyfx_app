/// Звукооператор: напряжённость момента → громкость слоёв (D-010).
/// Порт prototype/src/storyfx/mixer.py.
library;

import 'dart:collection';
import 'dart:math' as math;

import 'config.dart';

class SoundMixer {
  final double Function() clock;
  String mood;
  double intensity;
  final bool useTempo; // набор текста: темп набора — не темп рассказа
  final Queue<double> _wordTimes = Queue();
  int _seenInUtt = 0;
  double? _lastT;

  SoundMixer({required this.clock, this.mood = 'calm', this.useTempo = true})
      : intensity = moodIntensity[mood] ?? 0.3;

  /// Каждое событие распознавания: сколько слов во фразе сейчас. Новые слова — отметки времени.
  void onWords(int nWords, bool final_) {
    final now = clock();
    if (nWords > _seenInUtt) {
      for (var i = 0; i < nWords - _seenInUtt; i++) {
        _wordTimes.addLast(now);
      }
      _seenInUtt = nWords;
    }
    if (final_) _seenInUtt = 0;
    while (_wordTimes.isNotEmpty && now - _wordTimes.first > tempoWindowS) {
      _wordTimes.removeFirst();
    }
  }

  /// Слов в секунду за окно; null — слов мало или темп не учитываем.
  double? tempo() {
    if (!useTempo || _wordTimes.length < tempoMinWords) return null;
    final span = math.max(clock() - _wordTimes.first, 2.0);
    return _wordTimes.length / span;
  }

  double target() {
    final m = moodIntensity[mood] ?? 0.3;
    final r = tempo();
    if (r == null) return m;
    final t = ((r - tempoSlow) / (tempoFast - tempoSlow)).clamp(0.0, 1.0);
    return (1 - tempoWeight) * m + tempoWeight * t;
  }

  /// Сдвинуть напряжённость к цели (плавно, по прошедшему времени).
  double update() {
    final now = clock();
    final dt = _lastT == null ? 0.0 : math.max(0.0, now - _lastT!);
    _lastT = now;
    final k = 1 - math.exp(-dt / intensityTauS);
    intensity += (target() - intensity) * k;
    return intensity;
  }

  /// (фон, наложения, действия+персонажи, музыка) для текущей напряжённости.
  (double, double, double, double) levels() {
    final a = intensity;
    return (
      mixCalm.$1 + (mixIntense.$1 - mixCalm.$1) * a,
      mixCalm.$2 + (mixIntense.$2 - mixCalm.$2) * a,
      mixCalm.$3 + (mixIntense.$3 - mixCalm.$3) * a,
      mixCalm.$4 + (mixIntense.$4 - mixCalm.$4) * a,
    );
  }
}
