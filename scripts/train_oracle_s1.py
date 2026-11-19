"""Train <1 MB pure-NumPy `dolymarket-s1` oracle clarity + category student."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

DOLY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DOLY_ROOT))

from app.services.oracle import compute_clarity_score  # noqa: E402

NOUL_KEYS = [
    "has_authoritative_source",
    "has_unambiguous_predicate",
    "has_explicit_deadline",
    "has_subjective_ambiguity",
    "is_resolvable_market",
]

CATEGORIES = ["Crypto", "Macro", "Politics", "Sports", "Tech", "PopCulture", "Other"]


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -30.0, 30.0)))


def _softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - np.max(x, axis=-1, keepdims=True))
    return e / np.sum(e, axis=-1, keepdims=True)


def fit_soft_logistic(X: np.ndarray, y: np.ndarray, reg: float = 5e-4, steps: int = 500, lr: float = 1.5) -> tuple[np.ndarray, float]:
    n, d = X.shape
    w = np.zeros(d, dtype=np.float32)
    b = 0.0
    for _ in range(steps):
        p = _sigmoid(X @ w + b)
        err = p - y
        w -= lr * ((X.T @ err) / n + reg * w)
        b -= lr * float(np.mean(err))
    return w, b


def fit_soft_softmax(X: np.ndarray, probs_y: np.ndarray, reg: float = 5e-4, steps: int = 500, lr: float = 1.5) -> tuple[np.ndarray, np.ndarray]:
    n, d = X.shape
    k = probs_y.shape[1]
    W = np.zeros((d, k), dtype=np.float32)
    b = np.zeros(k, dtype=np.float32)
    for _ in range(steps):
        p = _softmax(X @ W + b)
        err = p - probs_y
        W -= lr * ((X.T @ err) / n + reg * W)
        b -= lr * np.mean(err, axis=0)
    return W, b


def load_jsonl(p: Path) -> List[Dict[str, Any]]:
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]


def main() -> None:
    tr = load_jsonl(DOLY_ROOT / "data" / "distill" / "train.jsonl")
    ho = load_jsonl(DOLY_ROOT / "data" / "distill" / "holdout.jsonl")

    tr_txt = [r["state"] for r in tr]
    ho_txt = [r["state"] for r in ho]

    vw = TfidfVectorizer(ngram_range=(1, 3), max_features=6000, sublinear_tf=True, min_df=2)
    vc = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), max_features=6000, sublinear_tf=True, min_df=3)
    X_tr = np.hstack([vw.fit_transform(tr_txt).astype(np.float32).toarray(), vc.fit_transform(tr_txt).astype(np.float32).toarray()])
    X_ho = np.hstack([vw.transform(ho_txt).astype(np.float32).toarray(), vc.transform(ho_txt).astype(np.float32).toarray()])

    t0 = time.perf_counter()
    W_noul, b_noul = [], []
    for k in NOUL_KEYS:
        y = np.array([r["teacher"][k] for r in tr], dtype=np.float32)
        w, b = fit_soft_logistic(X_tr, y)
        W_noul.append(w)
        b_noul.append(b)
    W_noul_arr = np.stack(W_noul)
    b_noul_arr = np.array(b_noul, dtype=np.float32)

    cat_y = np.array([[r["teacher"]["category_probs"].get(c, 0.0) for c in CATEGORIES] for r in tr], dtype=np.float32)
    cat_y /= np.maximum(1e-6, cat_y.sum(axis=1, keepdims=True))
    W_cat, b_cat = fit_soft_softmax(X_tr, cat_y)
    train_s = time.perf_counter() - t0

    out_dir = DOLY_ROOT / "app" / "models" / "dolymarket_s1"
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "vocab_word": {k: int(v) for k, v in vw.vocabulary_.items()},
        "idf_word": vw.idf_.astype(np.float16).tolist(),
        "vocab_char": {k: int(v) for k, v in vc.vocabulary_.items()},
        "idf_char": vc.idf_.astype(np.float16).tolist(),
        "noul_keys": NOUL_KEYS,
        "categories": CATEGORIES,
    }
    (out_dir / "meta.json").write_text(json.dumps(meta))
    np.savez_compressed(
        out_dir / "weights.npz",
        W_noul=W_noul_arr.astype(np.float16),
        b_noul=b_noul_arr.astype(np.float16),
        W_cat=W_cat.astype(np.float16),
        b_cat=b_cat.astype(np.float16),
    )
    total_bytes = (out_dir / "meta.json").stat().st_size + (out_dir / "weights.npz").stat().st_size

    # Evaluate on 150 unseen holdout markets vs regex compute_clarity_score
    t_inf0 = time.perf_counter()
    p_noul = _sigmoid(X_ho @ W_noul_arr.astype(np.float16).astype(np.float32).T + b_noul_arr)
    p_cat = _softmax(X_ho @ W_cat.astype(np.float16).astype(np.float32) + b_cat)
    inf_ms = (time.perf_counter() - t_inf0) * 1000 / len(ho)

    s1_res_ok = rx_res_ok = cat_ok = 0
    for i, r in enumerate(ho):
        t = r["teacher"]
        t_resolvable = t["is_resolvable_market"] >= 0.5
        s1_resolvable = bool(p_noul[i, 4] >= 0.5)
        rx = compute_clarity_score(
            r["resolution_criteria"],
            question=r["question"],
            end_date=r["end_date"] or None,
            oracle_feed=r["oracle_feed"] or None,
        )
        rx_resolvable = rx["score"] >= 50

        s1_res_ok += int(s1_resolvable == t_resolvable)
        rx_res_ok += int(rx_resolvable == t_resolvable)
        cat_ok += int(CATEGORIES[int(np.argmax(p_cat[i]))] == t["category"])

    print(f"Trained dolymarket-s1 in {train_s:.2f}s | dims={X_tr.shape[1]} | size={total_bytes/1024/1024:.2f} MB ({total_bytes:,} bytes)")
    print(f"Holdout (150 unseen markets) | inference={inf_ms:.3f} ms/market")
    print(f"  Resolvable Gate vs Jev : regex={rx_res_ok}/150 ({rx_res_ok/150:.1%}) | dolymarket-s1={s1_res_ok}/150 ({s1_res_ok/150:.1%})")
    print(f"  7-Way Category vs Jev  : dolymarket-s1={cat_ok}/150 ({cat_ok/150:.1%})")


if __name__ == "__main__":
    main()
