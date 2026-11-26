/// Токенизация, стемминг и сопоставление фраз-шаблонов — порт prototype/src/storyfx/textnorm.py.
library;

import 'config.dart';
import 'russian_stemmer.dart';

class Token {
  final String word;
  final String stem;
  const Token(this.word, this.stem);
}

final _wordRe = RegExp(r'[а-яa-z0-9]+');

String normalize(String text) => text.toLowerCase().replaceAll('ё', 'е');

List<Token> tokenize(String text) => _wordRe
    .allMatches(normalize(text))
    .map((m) {
      final w = m.group(0)!;
      return Token(w, stem(w));
    })
    .toList();

List<String> tokenizeWords(String text) => tokenize(text).map((t) => t.word).toList();

// ---------- прямая речь (только для текста: у микрофона кавычек нет) ----------
const speechOpen = '⟦';
const speechClose = '⟧';
const _dashes = '—–';

/// Пометить реплики: «…» и строки, начатые тире.
String markSpeech(String text) {
  final out = <String>[];
  for (var line in text.split('\n')) {
    final body = line.trimLeft();
    if ((body.isNotEmpty && _dashes.contains(body[0])) || body.startsWith('- ')) {
      final parts = body.substring(1).split(RegExp(r'\s[—–-]\s'));
      final rebuilt = <String>[];
      for (var i = 0; i < parts.length; i++) {
        rebuilt.add(i % 2 == 0 ? '$speechOpen${parts[i]}$speechClose' : parts[i]);
      }
      line = rebuilt.join(' ');
    }
    out.add(line
        .replaceAll('«', speechOpen)
        .replaceAll('»', speechClose)
        .replaceAll('„', speechOpen)
        .replaceAll('“', speechClose));
  }
  return out.join('\n');
}

/// Текст с метками ⟦ ⟧ → слова, маска «в реплике», состояние в конце.
/// NB: Dart split не сохраняет захваченные группы (в отличие от Python re.split) — сканируем вручную.
(List<String>, List<bool>, bool) speechWords(String text, [bool inSpeech = false]) {
  final words = <String>[], mask = <bool>[];
  final buf = StringBuffer();
  void flush() {
    if (buf.isEmpty) return;
    final ws = tokenizeWords(buf.toString());
    words.addAll(ws);
    mask.addAll(List.filled(ws.length, inSpeech));
    buf.clear();
  }

  for (final ch in text.split('')) {
    if (ch == speechOpen) {
      flush();
      inSpeech = true;
    } else if (ch == speechClose) {
      flush();
      inSpeech = false;
    } else {
      buf.write(ch);
    }
  }
  flush();
  return (words, mask, inSpeech);
}

// ---------- шаблоны ----------

enum PatternWordKind { prefix, stem, word }

class PatternWord {
  final PatternWordKind kind;
  final String value;
  const PatternWord(this.kind, this.value);

  bool matches(Token tok) => switch (kind) {
        PatternWordKind.prefix => tok.word.startsWith(value),
        PatternWordKind.stem => tok.stem == value,
        PatternWordKind.word => tok.word == value,
      };
}

class Pattern {
  final List<PatternWord> words;
  final String source;
  const Pattern(this.words, this.source);

  /// Длиннее и точнее — важнее (для разрешения пересечений).
  (int, int) get specificity =>
      (words.length, words.where((w) => w.kind != PatternWordKind.prefix).length);
}

Pattern parsePattern(String phrase) {
  final words = <PatternWord>[];
  for (var raw in phrase.split(' ')) {
    final exact = raw.startsWith('=');
    raw = normalize(raw.replaceFirst('=', ''));
    if (raw.isEmpty) continue;
    if (exact) {
      words.add(PatternWord(PatternWordKind.word, raw));
    } else if (raw.endsWith('*')) {
      words.add(PatternWord(PatternWordKind.prefix, raw.substring(0, raw.length - 1)));
    } else {
      final s = stem(raw);
      // слишком короткая основа («вой» → «во») совпадёт с предлогами — сравниваем слово целиком
      words.add(s.length >= 3
          ? PatternWord(PatternWordKind.stem, s)
          : PatternWord(PatternWordKind.word, raw));
    }
  }
  if (words.isEmpty) throw ArgumentError('пустая фраза: "$phrase"');
  return Pattern(words, phrase);
}

class Match {
  final Pattern pattern;
  final int start;
  final int end; // индекс последнего слова совпадения (включительно)
  const Match(this.pattern, this.start, this.end);
}

List<Match> findMatches(Pattern pattern, List<Token> tokens,
    [int maxGap = maxGapWords]) {
  final out = <Match>[];
  final first = pattern.words[0];
  final rest = pattern.words.sublist(1);
  for (var i = 0; i < tokens.length; i++) {
    if (!first.matches(tokens[i])) continue;
    var pos = i;
    var ok = true;
    for (final pw in rest) {
      var found = false;
      final to = (pos + 2 + maxGap).clamp(0, tokens.length);
      for (var j = pos + 1; j < to; j++) {
        if (pw.matches(tokens[j])) {
          pos = j;
          found = true;
          break;
        }
      }
      if (!found) {
        ok = false;
        break;
      }
    }
    if (ok) out.add(Match(pattern, i, pos));
  }
  return out;
}

// ---------- отрицание, сравнение, пересказ ----------

/// «как гроза», «словно медведь» — сравнение; «слушали, как трещат дрова» — придаточное, не сравнение.
bool isComparison(List<Token> tokens, int start) {
  if (start == 0 || !simileWords.contains(tokens[start - 1].word)) return false;
  const perception = similePerception;
  return !(start >= 2 &&
      (tokens[start - 2].stem.startsWith(perception.$1) ||
          tokens[start - 2].stem.startsWith(perception.$2) ||
          tokens[start - 2].stem.startsWith(perception.$3) ||
          tokens[start - 2].stem.startsWith(perception.$4) ||
          tokens[start - 2].stem.startsWith(perception.$5) ||
          tokens[start - 2].stem.startsWith(perception.$6)));
}

/// «не упал», «без дождя» — отрицание перед словом; «дождя нет», «дождя не было» — после.
bool isNegated(List<Token> tokens, int start,
    {int window = negationWindow, int? end}) {
  final from = start - window < 0 ? 0 : start - window;
  for (var i = from; i < start; i++) {
    if (negations.contains(tokens[i].word)) return true;
  }
  final after = tokens.sublist((end ?? start) + 1).take(2).map((t) => t.word).toList();
  return (after.isNotEmpty && after[0] == 'нет') ||
      (after.length > 1 && after[0] == 'не' && after[1].startsWith('был'));
}

/// Слова пересказа и союзы пересказа — из scenes.yaml (reported_words / reported_connectors).
/// Заполняются один раз при загрузке данных (scenes.dart).
List<Pattern> reportedWords = [];
Set<String> reportedConnectors = {'что'};

/// «стражник рассказал, что на кладбище…» — пересказ: место, погода и персонаж —
/// о чём говорят, а не кто и где на сцене.
bool isReported(List<Token> tokens, int start) {
  final say = <int>[];
  for (final p in reportedWords) {
    for (final m in findMatches(p, tokens.sublist(0, start))) {
      say.add(m.start);
    }
  }
  for (final i in say) {
    for (var j = i + 1; j < start; j++) {
      if (reportedConnectors.contains(tokens[j].word)) return true;
    }
  }
  return false;
}
