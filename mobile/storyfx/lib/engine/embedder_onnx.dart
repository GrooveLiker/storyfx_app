/// Модель смысла rubert-tiny2 на устройстве: ONNX (int8, 29 МБ) + WordPiece.
/// Векторы совпадают с Python-эталоном (проверка при экспорте —
/// prototype/tools/export_embedder_onnx.py, решения классификатора 100%).
library;

import 'dart:typed_data';

import 'package:flutter/services.dart' show rootBundle;
import 'package:onnxruntime/onnxruntime.dart';

import 'actions.dart' show Embedder;
import 'tokenizer.dart';

class OnnxEmbedder implements Embedder {
  final OrtSession _session;
  final WordPieceTokenizer _tok;
  final OrtRunOptions _runOptions = OrtRunOptions();

  OnnxEmbedder._(this._session, this._tok);

  static Future<OnnxEmbedder> load() async {
    OrtEnv.instance.init();
    final model =
        (await rootBundle.load('assets/model/rubert_tiny2.onnx')).buffer.asUint8List();
    final vocab = await rootBundle.loadString('assets/model/vocab.txt');
    final session = OrtSession.fromBuffer(model, OrtSessionOptions());
    return OnnxEmbedder._(session, WordPieceTokenizer.fromVocabText(vocab));
  }

  void release() {
    _runOptions.release();
    _session.release();
    OrtEnv.instance.release();
  }

  @override
  List<List<double>> encode(List<String> texts) {
    final batch = texts.length;
    final seq = _tok.maxLen;
    final ids = Int64List(batch * seq);
    final mask = Int64List(batch * seq);
    for (var i = 0; i < batch; i++) {
      final (ti, tm) = _tok.encode(texts[i]);
      ids.setRange(i * seq, (i + 1) * seq, ti);
      mask.setRange(i * seq, (i + 1) * seq, tm);
    }
    final shape = [batch, seq];
    final inIds = OrtValueTensor.createTensorWithDataList(ids, shape);
    final inMask = OrtValueTensor.createTensorWithDataList(mask, shape);
    final outputs =
        _session.run(_runOptions, {'input_ids': inIds, 'attention_mask': inMask});
    inIds.release();
    inMask.release();
    final raw = outputs.first?.value;
    for (final o in outputs) {
      o?.release();
    }
    return [
      for (final row in raw as List)
        [for (final x in row as List) (x as num).toDouble()]
    ];
  }
}
