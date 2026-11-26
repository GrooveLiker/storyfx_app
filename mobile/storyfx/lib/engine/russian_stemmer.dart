/// Русский стеммер Snowball — порт snowballstemmer (Python, russian.sbl, Snowball 3.1.1)
/// один в один, чтобы основы слов совпадали с ПК-прототипом побуквенно.
/// Источник: prototype/.venv/Lib/site-packages/snowballstemmer/russian_stemmer.py
library;

class _Among {
  final String s;
  final int substringI;
  final int result;
  const _Among(this.s, this.substringI, this.result);
}

class RussianStemmer {
  static const _v = {'а', 'е', 'и', 'о', 'у', 'ы', 'э', 'ю', 'я'};

  static const _a0 = [
    _Among('в', -1, 1), _Among('ив', 0, 2), _Among('ыв', 0, 2),
    _Among('вши', -1, 1), _Among('ивши', 3, 2), _Among('ывши', 3, 2),
    _Among('вшись', -1, 1), _Among('ившись', 6, 2), _Among('ывшись', 6, 2),
  ];
  static const _a1 = [
    _Among('ее', -1, 1), _Among('ие', -1, 1), _Among('ое', -1, 1), _Among('ые', -1, 1),
    _Among('ими', -1, 1), _Among('ыми', -1, 1), _Among('ей', -1, 1), _Among('ий', -1, 1),
    _Among('ой', -1, 1), _Among('ый', -1, 1), _Among('ем', -1, 1), _Among('им', -1, 1),
    _Among('ом', -1, 1), _Among('ым', -1, 1), _Among('его', -1, 1), _Among('ого', -1, 1),
    _Among('ему', -1, 1), _Among('ому', -1, 1), _Among('их', -1, 1), _Among('ых', -1, 1),
    _Among('ею', -1, 1), _Among('ою', -1, 1), _Among('ую', -1, 1), _Among('юю', -1, 1),
    _Among('ая', -1, 1), _Among('яя', -1, 1),
  ];
  static const _a2 = [
    _Among('ем', -1, 1), _Among('нн', -1, 1), _Among('вш', -1, 1), _Among('ивш', 2, 2),
    _Among('ывш', 2, 2), _Among('щ', -1, 1), _Among('ющ', 5, 1), _Among('ующ', 6, 2),
  ];
  static const _a3 = [_Among('сь', -1, 1), _Among('ся', -1, 1)];
  static const _a4 = [
    _Among('ла', -1, 1), _Among('ила', 0, 2), _Among('ыла', 0, 2), _Among('на', -1, 1),
    _Among('ена', 3, 2), _Among('ете', -1, 1), _Among('ите', -1, 2), _Among('йте', -1, 1),
    _Among('ейте', 7, 2), _Among('уйте', 7, 2), _Among('ли', -1, 1), _Among('или', 10, 2),
    _Among('ыли', 10, 2), _Among('й', -1, 1), _Among('ей', 13, 2), _Among('уй', 13, 2),
    _Among('л', -1, 1), _Among('ил', 16, 2), _Among('ыл', 16, 2), _Among('ем', -1, 1),
    _Among('им', -1, 2), _Among('ым', -1, 2), _Among('н', -1, 1), _Among('ен', 22, 2),
    _Among('ло', -1, 1), _Among('ило', 24, 2), _Among('ыло', 24, 2), _Among('но', -1, 1),
    _Among('ено', 27, 2), _Among('нно', 27, 1), _Among('ет', -1, 1), _Among('ует', 30, 2),
    _Among('ит', -1, 2), _Among('ыт', -1, 2), _Among('ют', -1, 1), _Among('уют', 34, 2),
    _Among('ят', -1, 2), _Among('ны', -1, 1), _Among('ены', 37, 2), _Among('ть', -1, 1),
    _Among('ить', 39, 2), _Among('ыть', 39, 2), _Among('ешь', -1, 1), _Among('ишь', -1, 2),
    _Among('ю', -1, 2), _Among('ую', 44, 2),
  ];
  static const _a5 = [
    _Among('а', -1, 1), _Among('ев', -1, 1), _Among('ов', -1, 1), _Among('е', -1, 1),
    _Among('ие', 3, 1), _Among('ье', 3, 1), _Among('и', -1, 1), _Among('еи', 6, 1),
    _Among('ии', 6, 1), _Among('ами', 6, 1), _Among('ями', 6, 1), _Among('иями', 10, 1),
    _Among('й', -1, 1), _Among('ей', 12, 1), _Among('ией', 13, 1), _Among('ий', 12, 1),
    _Among('ой', 12, 1), _Among('ам', -1, 1), _Among('ем', -1, 1), _Among('ием', 18, 1),
    _Among('ом', -1, 1), _Among('ям', -1, 1), _Among('иям', 21, 1), _Among('о', -1, 1),
    _Among('у', -1, 1), _Among('ах', -1, 1), _Among('ях', -1, 1), _Among('иях', 26, 1),
    _Among('ы', -1, 1), _Among('ь', -1, 1), _Among('ю', -1, 1), _Among('ию', 30, 1),
    _Among('ью', 30, 1), _Among('я', -1, 1), _Among('ия', 33, 1), _Among('ья', 33, 1),
  ];
  static const _a6 = [_Among('ост', -1, 1), _Among('ость', -1, 1)];
  static const _a7 = [
    _Among('ейше', -1, 1), _Among('н', -1, 2), _Among('ейш', -1, 1), _Among('ь', -1, 3),
  ];

  // состояние BaseStemmer; строка — как список символов (русский — BMP, code units == символы)
  List<String> _cur = [];
  int _cursor = 0, _limit = 0, _limitBackward = 0, _bra = 0, _ket = 0;
  int _pV = 0, _p2 = 0;

  String stemWord(String word) {
    _cur = word.split('');
    _cursor = 0;
    _limit = _cur.length;
    _limitBackward = 0;
    _bra = _cursor;
    _ket = _limit;
    _stem();
    return _cur.sublist(0, _limit).join();
  }

  // ---------- примитивы ----------

  bool _goOutGrouping(Set<String> g) {
    while (_cursor < _limit) {
      if (g.contains(_cur[_cursor])) return true;
      _cursor++;
    }
    return false;
  }

  bool _goInGrouping(Set<String> g) {
    while (_cursor < _limit) {
      if (!g.contains(_cur[_cursor])) return true;
      _cursor++;
    }
    return false;
  }

  int _findAmongB(List<_Among> v) {
    var i = 0, j = v.length;
    final c = _cursor, lb = _limitBackward;
    var commonI = 0, commonJ = 0;
    var firstKeyInspected = false;
    while (true) {
      final k = i + ((j - i) >> 1);
      var diff = 0;
      var common = commonI < commonJ ? commonI : commonJ;
      final w = v[k];
      for (var i2 = w.s.length - 1 - common; i2 >= 0; i2--) {
        if (c - common == lb) { diff = -1; break; }
        diff = _cur[c - 1 - common].codeUnitAt(0) - w.s.codeUnitAt(i2);
        if (diff != 0) break;
        common++;
      }
      if (diff < 0) { j = k; commonJ = common; } else { i = k; commonI = common; }
      if (j - i <= 1) {
        if (i > 0 || j == i || firstKeyInspected) break;
        firstKeyInspected = true;
      }
    }
    while (true) {
      final w = v[i];
      if (commonI >= w.s.length) {
        _cursor = c - w.s.length;
        return w.result;
      }
      i = w.substringI;
      if (i < 0) return 0;
    }
  }

  void _replaceS(int cBra, int cKet, String s) {
    final adjustment = s.length - (cKet - cBra);
    _cur = [..._cur.sublist(0, cBra), ...s.split(''), ..._cur.sublist(cKet)];
    _limit += adjustment;
    if (_cursor >= cKet) {
      _cursor += adjustment;
    } else if (_cursor > cBra) {
      _cursor = cBra;
    }
  }

  void _sliceFrom(String s) {
    _replaceS(_bra, _ket, s);
    _ket = _bra + s.length;
  }

  void _sliceDel() => _sliceFrom('');

  // ---------- шаги ----------

  void _rMarkRegions() {
    _pV = _limit;
    _p2 = _limit;
    final v1 = _cursor;
    // lab0: любая неудача — выйти, восстановив курсор
    if (_goOutGrouping(_v)) {
      _cursor++;
      _pV = _cursor;
      if (_goInGrouping(_v)) {
        _cursor++;
        if (_goOutGrouping(_v)) {
          _cursor++;
          if (_goInGrouping(_v)) {
            _cursor++;
            _p2 = _cursor;
          }
        }
      }
    }
    _cursor = v1;
  }

  bool _rPerfectiveGerund() {
    _ket = _cursor;
    final amongVar = _findAmongB(_a0);
    if (amongVar == 0) return false;
    _bra = _cursor;
    if (amongVar == 1) {
      // [а/я] перед совпадением
      if (_cursor <= _limitBackward || _cur[_cursor - 1] != 'а') {
        if (_cursor <= _limitBackward || _cur[_cursor - 1] != 'я') return false;
        _cursor--;
      } else {
        _cursor--;
      }
      _sliceDel();
    } else {
      _sliceDel();
    }
    return true;
  }

  bool _rAdjective() {
    _ket = _cursor;
    if (_findAmongB(_a1) == 0) return false;
    _bra = _cursor;
    _sliceDel();
    return true;
  }

  bool _rAdjectival() {
    if (!_rAdjective()) return false;
    final v1 = _limit - _cursor;
    // try: [а/я] + суффикс причастия; неудача — откат и выход без ошибки
    _ket = _cursor;
    final amongVar = _findAmongB(_a2);
    if (amongVar == 0) {
      _cursor = _limit - v1;
      return true;
    }
    _bra = _cursor;
    if (amongVar == 1) {
      if (_cursor <= _limitBackward || _cur[_cursor - 1] != 'а') {
        if (_cursor <= _limitBackward || _cur[_cursor - 1] != 'я') {
          _cursor = _limit - v1;
          return true;
        }
        _cursor--;
      } else {
        _cursor--;
      }
      _sliceDel();
    } else {
      _sliceDel();
    }
    return true;
  }

  bool _rReflexive() {
    _ket = _cursor;
    if (_findAmongB(_a3) == 0) return false;
    _bra = _cursor;
    _sliceDel();
    return true;
  }

  bool _rVerb() {
    _ket = _cursor;
    final amongVar = _findAmongB(_a4);
    if (amongVar == 0) return false;
    _bra = _cursor;
    if (amongVar == 1) {
      if (_cursor <= _limitBackward || _cur[_cursor - 1] != 'а') {
        if (_cursor <= _limitBackward || _cur[_cursor - 1] != 'я') return false;
        _cursor--;
      } else {
        _cursor--;
      }
      _sliceDel();
    } else {
      _sliceDel();
    }
    return true;
  }

  bool _rNoun() {
    _ket = _cursor;
    if (_findAmongB(_a5) == 0) return false;
    _bra = _cursor;
    _sliceDel();
    return true;
  }

  bool _rDerivational() {
    _ket = _cursor;
    if (_findAmongB(_a6) == 0) return false;
    _bra = _cursor;
    if (_p2 > _cursor) return false;
    _sliceDel();
    return true;
  }

  bool _rTidyUp() {
    _ket = _cursor;
    final amongVar = _findAmongB(_a7);
    if (amongVar == 0) return false;
    _bra = _cursor;
    if (amongVar == 1) {
      _sliceDel();
      _ket = _cursor;
      if (_cursor <= _limitBackward || _cur[_cursor - 1] != 'н') return false;
      _cursor--;
      _bra = _cursor;
      if (_cursor <= _limitBackward || _cur[_cursor - 1] != 'н') return false;
      _cursor--;
      _sliceDel();
    } else if (amongVar == 2) {
      if (_cursor <= _limitBackward || _cur[_cursor - 1] != 'н') return false;
      _cursor--;
      _sliceDel();
    } else {
      _sliceDel();
    }
    return true;
  }

  // ---------- главный шаг ----------

  void _stem() {
    // ё → е по всему слову
    final v1 = _cursor;
    _cursor = 0;
    while (_cursor < _limit) {
      if (_cur[_cursor] == 'ё') {
        _bra = _cursor;
        _cursor++;
        _ket = _cursor;
        _sliceFrom('е');
      } else {
        _cursor++;
      }
    }
    _cursor = v1;
    _rMarkRegions();
    _limitBackward = _cursor;
    _cursor = _limit;
    if (_cursor < _pV) return;
    final v5 = _limitBackward;
    _limitBackward = _pV;
    // perfective_gerund | (reflexive)? (adjectival | verb | noun)
    // ВАЖНО: в оригинале курсор возвращается в конец слова (limit) перед каждым шагом.
    if (!_rPerfectiveGerund()) {
      _cursor = _limit;
      _rReflexive(); // ошибка игнорируется
      _cursor = _limit;
      if (!_rAdjectival()) {
        _cursor = _limit;
        if (!_rVerb()) {
          _cursor = _limit;
          _rNoun();
        }
      }
    }
    // конечное «и»
    _cursor = _limit;
    if (_cursor > _limitBackward && _cur[_cursor - 1] == 'и') {
      _ket = _cursor;
      _cursor--;
      _bra = _cursor;
      _sliceDel();
    }
    _cursor = _limit;
    _rDerivational();
    _cursor = _limit;
    _rTidyUp();
    _limitBackward = v5;
    _cursor = _limitBackward;
  }
}

/// Кэш как в Python (`lru_cache`): стеммер вызывается на каждом слове каждой фразы.
final _stemCache = <String, String>{};

String stem(String word) =>
    _stemCache.putIfAbsent(word, () => RussianStemmer().stemWord(word));
