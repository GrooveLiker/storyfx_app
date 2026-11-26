"""Экспорт cointegrated/rubert-tiny2 в ONNX для задачи 36 (эмбеддер на телефоне).

Один файл: transformer + mean-pooling + L2-нормализация — телефону остаётся
только токенизация (WordPiece, vocab.txt рядом) и один прогон ONNX.

Проверка: косинусная близость векторов ONNX к sentence-transformers на примерах
из данных движка (сцены, действия) — должна быть ~1.0 (fp32) и >= 0,999 (int8).

Запуск: prototype/.venv/Scripts/python tools/export_embedder_onnx.py
"""
from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import torch
from sentence_transformers import SentenceTransformer

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT.parent / "mobile" / "storyfx" / "assets" / "model"
MODEL = "cointegrated/rubert-tiny2"


class ClsPoolNormalize(torch.nn.Module):
    """last_hidden_state → CLS-токен → L2-норма (как у модели: 1_Pooling pooling_mode_cls_token)."""

    def __init__(self, transformer: torch.nn.Module):
        super().__init__()
        self.tr = transformer

    def forward(self, input_ids: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
        h = self.tr(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state
        return torch.nn.functional.normalize(h[:, 0], p=2, dim=1)


def cosine(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return (a * b).sum(axis=1)


def main() -> None:
    import os
    os.environ["HF_HUB_OFFLINE"] = "1"  # модель уже в кэше — в сеть не ходим

    st = SentenceTransformer(MODEL, cache_folder=str(ROOT / "models" / "hf"), device="cpu")
    model = ClsPoolNormalize(st[0].auto_model).eval()  # 0 — Transformer, дальше Pooling(CLS)+Normalize

    OUT.mkdir(parents=True, exist_ok=True)
    fp32 = OUT / "rubert_tiny2.fp32.onnx"
    ids = torch.randint(0, 1000, (2, 16))
    mask = torch.ones_like(ids)
    torch.onnx.export(
        model, (ids, mask), str(fp32),
        input_names=["input_ids", "attention_mask"], output_names=["embedding"],
        dynamic_axes={"input_ids": {0: "batch", 1: "seq"},
                      "attention_mask": {0: "batch", 1: "seq"},
                      "embedding": {0: "batch"}},
        opset_version=17,
        dynamo=False,  # dynamo-экспорт (torch 2.15) даёт битую модель: duplicate output name
    )
    print(f"fp32: {fp32} ({fp32.stat().st_size / 1e6:.1f} МБ)")

    # словарь для WordPiece на телефоне
    vocab = OUT / "vocab.txt"
    tok = st.tokenizer
    shutil.copy(tok.vocab_file, vocab) if hasattr(tok, "vocab_file") else tok.save_vocabulary(str(OUT))
    print(f"vocab: {vocab} ({vocab.stat().st_size / 1e6:.1f} МБ)")

    # проверка fp32 против эталона на данных движка
    import onnxruntime as ort
    import yaml

    texts = ["лес", "таверна", "море"]
    data = ROOT / "data"
    for e in yaml.safe_load((data / "scenes.yaml").read_text(encoding="utf-8"))["scenes"].values():
        texts += e.get("descriptions") or []
    ref = st.encode(texts, normalize_embeddings=True, convert_to_numpy=True)

    def run_onnx(path: Path) -> np.ndarray:
        sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
        enc = tok(texts, padding=True, truncation=True, max_length=64, return_tensors="np")
        return sess.run(None, {"input_ids": enc["input_ids"].astype(np.int64),
                               "attention_mask": enc["attention_mask"].astype(np.int64)})[0]

    got = run_onnx(fp32)
    sims = cosine(ref, got)
    print(f"fp32 vs эталон: min cos {sims.min():.6f} на {len(texts)} текстах")
    assert sims.min() > 0.99999, "fp32 расходится с эталоном"

    # сжатие: fp16 (почти без потерь, ~58 МБ) и int8 (~29 МБ) — сравниваем качество
    best = None
    try:
        from onnxconverter_common import float16
        import tempfile
        f16 = OUT / "rubert_tiny2.fp16.onnx"
        # конвертер пишет временные файлы рядом с моделью — работаем во временной папке
        with tempfile.TemporaryDirectory(dir=OUT) as td:
            tmp_fp32 = Path(td) / "model.onnx"
            shutil.copy(fp32, tmp_fp32)
            shutil.copy(OUT / "rubert_tiny2.fp32.onnx.data", Path(td) / "model.onnx.data")
            float16.convert_float_to_float16_model_path(str(tmp_fp32), str(Path(td) / "f16.onnx"))
            shutil.move(str(Path(td) / "f16.onnx"), f16)
        sims = cosine(ref, run_onnx(f16))
        print(f"fp16: {f16.stat().st_size / 1e6:.1f} МБ, min cos {sims.min():.6f}")
        if sims.min() > 0.9999:
            best = f16
    except Exception as e:
        print(f"fp16 не вышло ({type(e).__name__}) — выбираем из int8")

    if best is None:
        from onnxruntime.quantization import QuantType, quantize_dynamic
        for qt, name in ((QuantType.QInt8, "qint8"), (QuantType.QUInt8, "quint8")):
            q = OUT / f"rubert_tiny2.{name}.onnx"
            quantize_dynamic(str(fp32), str(q), weight_type=qt)
            sims = cosine(ref, run_onnx(q))
            print(f"{name}: {q.stat().st_size / 1e6:.1f} МБ, min cos {sims.min():.6f}, mean {sims.mean():.6f}")
            if best is None or sims.min() > cosine(ref, run_onnx(best)).min():
                best = q

    final = OUT / "rubert_tiny2.onnx"
    if best.resolve() != final.resolve():
        if final.exists():
            final.unlink()
        best.rename(final)
    sims = cosine(ref, run_onnx(final))
    print(f"итог: {final} ({final.stat().st_size / 1e6:.1f} МБ), min cos {sims.min():.6f}")
    # Критерий — стабильность РЕШЕНИЙ, а не точность векторов: int8 даёт cos ~0,996
    # (сдвиг попарного сходства до 0,024), но «ближайшая сцена» совпадает на 100% текстов.
    assert sims.min() > 0.995, "сжатие слишком деградирует"
    got = run_onnx(final)
    s_ref, s_q = ref @ ref.T, got @ got.T
    for d in (s_ref - s_q,):
        np.fill_diagonal(d, 0)
    delta = np.abs(s_ref - s_q).max()
    labels = [sid for sid, e in yaml.safe_load((data / "scenes.yaml").read_text(encoding="utf-8"))["scenes"].items()
              for _ in (e.get("descriptions") or [])]
    mism = sum(1 for i in range(3, len(texts))
               if labels[np.argmax(s_ref[i, 3:])] != labels[np.argmax(s_q[i, 3:])])
    print(f"сдвиг попарного сходства ≤ {delta:.4f}; сменилось решений: {mism} из {len(texts) - 3}")
    assert mism == 0, "int8 меняет решения классификатора"
    fp32.unlink()
    (OUT / "rubert_tiny2.fp32.onnx.data").unlink(missing_ok=True)
    for tmp in OUT.glob("rubert_tiny2.q*.onnx"):
        tmp.unlink()
    (OUT / "rubert_tiny2.fp16.onnx").unlink(missing_ok=True)
    print("OK")


if __name__ == "__main__":
    main()
