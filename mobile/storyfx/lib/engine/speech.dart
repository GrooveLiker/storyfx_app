/// Реплики героев в речи без кавычек (голос): какие слова фразы — голос героя.
/// Порт prototype/src/storyfx/speech.py.
library;

import 'package:yaml/yaml.dart';

class SpeechCues {
  final int window;
  final Set<String> pronouns;
  final Set<String> firstPerson;
  final Set<String> imperatives;
  final List<String> narrationEndings;
  const SpeechCues(this.window, this.pronouns, this.firstPerson, this.imperatives,
      this.narrationEndings);

  bool _isCue(List<String> words, int i) {
    final w = words[i];
    if (pronouns.contains(w) || firstPerson.contains(w) || imperatives.contains(w)) return true;
    // обращение-повтор: «печка печка», «яблоня яблоня» (не «и и», не короткие слова)
    return w.length >= 3 && i + 1 < words.length && words[i + 1] == w;
  }

  bool _isNarration(String w) =>
      w.length >= 6 && narrationEndings.any((e) => w.endsWith(e));

  /// Слова (как в tokenize) → признак «в реплике» для каждого.
  List<bool> guess(List<String> words) {
    final mask = List<bool>.filled(words.length, false);
    for (var i = 0; i < words.length; i++) {
      if (!_isCue(words, i)) continue;
      mask[i] = true;
      if (i + 1 < words.length && words[i + 1] == words[i]) mask[i + 1] = true;
      for (var j = i + 1; j < words.length && j < i + 1 + window; j++) {
        if (_isNarration(words[j])) break;
        mask[j] = true;
      }
    }
    return mask;
  }
}

SpeechCues loadSpeechCues(String yamlText) {
  final raw = loadYaml(yamlText) as YamlMap;
  Set<String> norm(Iterable xs) =>
      {for (final x in xs) x.toString().toLowerCase().replaceAll('ё', 'е')};
  return SpeechCues(
      (raw['window'] as int?) ?? 3,
      norm((raw['pronouns'] as YamlList?) ?? const []),
      norm((raw['first_person'] as YamlList?) ?? const []),
      norm(((raw['imperatives'] as YamlList?) ?? const []).where((x) => !x.toString().contains(' '))),
      [for (final e in (raw['narration_endings'] as YamlList?) ?? const []) e.toString()]);
}
