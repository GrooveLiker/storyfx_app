/// WordPiece-токенизатор для rubert-tiny2 (BERT, регистр сохраняется —
/// do_lower_case: false). Порт поведения HuggingFace BertTokenizer:
/// basic-токены (пробелы + знаки препинания) → жадный WordPiece с «##».
library;

class WordPieceTokenizer {
  final Map<String, int> vocab;
  final int maxLen;
  final int clsId;
  final int sepId;
  final int unkId;

  WordPieceTokenizer(this.vocab,
      {this.maxLen = 64,
      this.clsId = 2, // vocab.txt: [PAD]=0, [UNK]=1, [CLS]=2, [SEP]=3
      this.sepId = 3,
      this.unkId = 1});

  /// vocab.txt: одна строка = один токен, номер строки (с 0) = id.
  static WordPieceTokenizer fromVocabText(String text, {int maxLen = 64}) {
    final vocab = <String, int>{};
    final lines = text.split('\n');
    for (var i = 0; i < lines.length; i++) {
      final t = lines[i].trimRight();
      if (t.isNotEmpty) vocab[t] = i;
    }
    return WordPieceTokenizer(vocab,
        maxLen: maxLen,
        clsId: vocab['[CLS]'] ?? 2,
        sepId: vocab['[SEP]'] ?? 3,
        unkId: vocab['[UNK]'] ?? 1);
  }

  static final _punct = RegExp(r'\p{P}|\p{S}', unicode: true);

  /// input_ids и attention_mask (с [CLS]/[SEP], дополнены [PAD]=0 до maxLen).
  (List<int>, List<int>) encode(String text) {
    final ids = <int>[clsId];
    for (final word in _basicTokens(text)) {
      if (ids.length >= maxLen - 1) break;
      ids.addAll(_wordPiece(word));
    }
    ids.add(sepId);
    final mask = List<int>.filled(ids.length, 1, growable: true);
    while (ids.length < maxLen) {
      ids.add(0);
      mask.add(0);
    }
    return (ids, mask);
  }

  /// Разбивка на слова и знаки препинания (basic tokenization, без CJK —
  /// для русского текста достаточно).
  Iterable<String> _basicTokens(String text) sync* {
    final buf = StringBuffer();
    for (final ch in text.runes.map(String.fromCharCode)) {
      if (_punct.hasMatch(ch)) {
        if (buf.isNotEmpty) {
          yield buf.toString();
          buf.clear();
        }
        yield ch;
      } else if (ch.trim().isEmpty) {
        if (buf.isNotEmpty) {
          yield buf.toString();
          buf.clear();
        }
      } else {
        buf.write(ch);
      }
    }
    if (buf.isNotEmpty) yield buf.toString();
  }

  /// Жадный longest-match-first с продолжениями «##». Нет совпадения — [UNK].
  List<int> _wordPiece(String word) {
    if (word.length > 100) return [unkId];
    final out = <int>[];
    var start = 0;
    while (start < word.length) {
      var end = word.length;
      var found = -1;
      while (end > start) {
        final piece = (start == 0 ? '' : '##') + word.substring(start, end);
        final id = vocab[piece];
        if (id != null) {
          found = id;
          break;
        }
        end--;
      }
      if (found < 0) return [unkId]; // неразборчивое слово целиком — [UNK]
      out.add(found);
      start = end;
    }
    return out;
  }
}
