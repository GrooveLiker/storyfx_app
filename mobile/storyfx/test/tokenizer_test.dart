/// Токенизатор сверен с HuggingFace BertTokenizer (cointegrated/rubert-tiny2).
library;

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:storyfx/engine/tokenizer.dart';

void main() {
  late WordPieceTokenizer tok;

  setUpAll(() {
    tok = WordPieceTokenizer.fromVocabText(
        File('assets/model/vocab.txt').readAsStringSync());
  });

  List<int> core(String text) {
    final (ids, _) = tok.encode(text);
    return ids.sublist(0, ids.indexOf(tok.sepId) + 1); // без паддинга
  }

  test('совпадает с HuggingFace на контрольных фразах', () {
    final expected = <String, List<int>>{
      'лес': [2, 32637, 3],
      'Отряд вошёл в густой лес': [2, 51830, 19459, 314, 56748, 32637, 3],
      'Жили-были дед да баба.': [2, 51365, 17, 1610, 44254, 791, 76286, 18, 3],
      'ковёр-самолёт': [2, 51451, 7687, 17, 23959, 3],
      'Ёжик шёл в тумане': [2, 266, 52675, 40617, 314, 76936, 3],
      'машиностроение123test': [2, 16093, 67396, 7670, 1113, 13628, 3],
    };
    for (final e in expected.entries) {
      expect(core(e.key), e.value, reason: e.key);
    }
  });

  test('маска и паддинг до maxLen', () {
    final (ids, mask) = tok.encode('лес');
    expect(ids.length, tok.maxLen);
    expect(mask.length, tok.maxLen);
    expect(mask.sublist(0, 3), [1, 1, 1]);
    expect(mask.sublist(3).every((m) => m == 0), isTrue);
    expect(ids.sublist(3).every((i) => i == 0), isTrue);
  });
}
