import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:storyfx/engine/russian_stemmer.dart';
import 'package:storyfx/engine/textnorm.dart';

void main() {
  test('стеммер совпадает с Python snowballstemmer на словаре проекта', () {
    final ref = jsonDecode(
            File('test/stem_reference.json').readAsStringSync())
        as Map<String, dynamic>;
    final wrong = <String>[];
    ref.forEach((word, expected) {
      final got = stem(word);
      if (got != expected) wrong.add('$word: $got != $expected');
    });
    expect(wrong, isEmpty,
        reason: '${wrong.length} расхождений из ${ref.length}: ${wrong.take(10).join("; ")}');
  });

  test('tokenize: ё→е, нижний регистр, только слова', () {
    final toks = tokenize('Ёжик, погладил лошадь!');
    expect(toks.map((t) => t.word), ['ежик', 'погладил', 'лошадь']);
  });

  test('шаблоны: основа, префикс, точное слово, пропуск', () {
    final toks = tokenize('ворота открылись медленно');
    expect(findMatches(parsePattern('ворота'), toks), hasLength(1));
    expect(findMatches(parsePattern('ворот*'), toks), hasLength(1));
    expect(findMatches(parsePattern('=ворота'), toks), hasLength(1));
    expect(findMatches(parsePattern('=ворот'), toks), isEmpty);
    // пропуск до maxGap слов между словами шаблона
    final toks2 = tokenize('открыл тяжёлые ворота');
    expect(findMatches(parsePattern('открыл ворота'), toks2), hasLength(1));
    expect(findMatches(parsePattern('ворота открыл'), toks2), isEmpty);
  });

  test('разметка реплик: кавычки и тире', () {
    final marked = markSpeech('— Печка, печка, скажи! — говорит девочка.');
    expect(marked, contains(speechOpen));
    final (words, mask, inSpeech) = speechWords(marked);
    expect(words, isNotEmpty);
    expect(mask.length, words.length);
    // «печка», «скажи» — в реплике, «говорит» — нет
    expect(mask[words.indexOf('печка')], isTrue);
    expect(mask[words.indexOf('говорит')], isFalse);
    expect(inSpeech, isFalse);
  });
}
