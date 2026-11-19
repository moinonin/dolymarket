"""Distill `oracle-s1` from TypeSafe `Jev` over MultiNLI + market scenarios,
then benchmark against 100 unseen public MultiNLI validation rows.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from typesafe_sdk import Noul, TypeSafeClient

DOLY_ROOT = Path(__file__).resolve().parents[1]
LABELS = ["YES_EVIDENCE", "NO_EVIDENCE", "INCONCLUSIVE"]
HF_NLI_URL = "https://datasets-server.huggingface.co/rows"


def _load_env() -> None:
    for env_path in (DOLY_ROOT / ".env", DOLY_ROOT.parent / "ai" / "githeri" / ".env"):
        if not env_path.exists():
            continue
        for ln in env_path.read_text().splitlines():
            if "=" in ln and not ln.strip().startswith("#"):
                k, v = ln.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def fetch_multinli(offset: int, length: int = 100) -> list[dict]:
    resp = httpx.get(
        HF_NLI_URL,
        params={
            "dataset": "nyu-mll/multi_nli",
            "config": "default",
            "split": "validation_matched",
            "offset": offset,
            "length": length,
        },
        timeout=20.0,
    )
    resp.raise_for_status()
    out = []
    # MultiNLI labels: 0=entailment (YES), 1=neutral (INCONCLUSIVE), 2=contradiction (NO)
    label_map = {0: 0, 2: 1, 1: 2}
    for item in resp.json()["rows"]:
        r = item["row"]
        if r.get("label") not in label_map:
            continue
        out.append(
            {
                "question": r["hypothesis"],
                "evidence": r["premise"],
                "gold": label_map[r["label"]],
                "source": "multi_nli",
            }
        )
    return out


def market_seed_rows() -> list[dict]:
    return [
        {"question": "Will the Fed cut rates in December?", "evidence": "FOMC cut federal funds rate by 25 bps today.", "gold": 0, "source": "market"},
        {"question": "Will the Fed cut rates in December?", "evidence": "Rates were not cut; FOMC kept target unchanged.", "gold": 1, "source": "market"},
        {"question": "Will the Fed cut rates in December?", "evidence": "Fed officials scheduled next policy symposium.", "gold": 2, "source": "market"},
        {"question": "Will Anthropic IPO before 2027?", "evidence": "Anthropic completed its Nasdaq IPO debut today.", "gold": 0, "source": "market"},
        {"question": "Will Anthropic IPO before 2027?", "evidence": "Anthropic denied IPO rumors and postponed listing.", "gold": 1, "source": "market"},
        {"question": "Will Anthropic IPO before 2027?", "evidence": "Anthropic released a new frontier model.", "gold": 2, "source": "market"},
        {"question": "Will Bitcoin close above $150k?", "evidence": "Bitcoin closed at $152,400 on Coinbase today.", "gold": 0, "source": "market"},
        {"question": "Will Bitcoin close above $150k?", "evidence": "Bitcoin remained below $120,000 all month.", "gold": 1, "source": "market"},
        {"question": "Will US CPI exceed 3.0%?", "evidence": "BLS reported CPI rose 3.2% year-over-year.", "gold": 0, "source": "market"},
        {"question": "Will US CPI exceed 3.0%?", "evidence": "BLS October CPI printed at 2.6%, below 3.0%.", "gold": 1, "source": "market"},
        {"question": "Will Senate pass the stablecoin bill?", "evidence": "The US Senate passed the stablecoin bill 68-30.", "gold": 0, "source": "market"},
        {"question": "Will Senate pass the stablecoin bill?", "evidence": "Senate rejected the bill after cloture failed.", "gold": 1, "source": "market"},
    ]


def distill_one(client: TypeSafeClient, row: dict) -> dict:
    resp = client.system_one(
        state={"claim_or_question": row["question"], "evidence": row["evidence"]},
        questions={
            "yes_ev": Noul(instructions="Does the evidence prove or entail the claim/YES outcome?"),
            "no_ev": Noul(instructions="Does the evidence contradict or disprove the claim/YES outcome?"),
        },
    )
    p_yes = float(resp.nouls["yes_ev"].noul)
    p_no = float(resp.nouls["no_ev"].noul)
    p_inc = max(0.05, 1.0 - max(p_yes, p_no))
    probs = np.array([p_yes, p_no, p_inc], dtype=np.float32)
    probs /= probs.sum()
    return {**row, "teacher_probs": probs.tolist()}


_STOPWORDS = frozenset({"the", "a", "an", "is", "are", "was", "were", "be", "been", "to", "of", "in", "on", "at", "for", "and", "or", "by", "with", "that", "this", "it", "will", "would", "can", "could", "has", "have", "had", "do", "does", "did"})
_NEG_WORDS = frozenset({"not", "no", "never", "neither", "nor", "none", "nothing", "nowhere", "without", "hardly", "barely", "scarcely", "denied", "rejected", "failed", "cancelled", "canceled", "postponed", "unchanged", "paused", "below", "less", "lower", "unlikely", "refused", "blocked", "stopped", "dropped"})
_WORD_RE = re.compile(r"[a-z0-9]+")
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def cross_features(q: str, ev: str) -> np.ndarray:
    """Domain-invariant pairwise alignment + negation features between claim and evidence."""
    qt = [t for t in _WORD_RE.findall(q.lower()) if t not in _STOPWORDS]
    et = [t for t in _WORD_RE.findall(ev.lower()) if t not in _STOPWORDS]
    qs, es = set(qt), set(et)
    overlap = len(qs & es) / max(1, len(qs))
    jaccard = len(qs & es) / max(1, len(qs | es))

    q_bi = set(zip(qt, qt[1:]))
    e_bi = set(zip(et, et[1:]))
    bi_overlap = len(q_bi & e_bi) / max(1, len(q_bi))

    q_neg = sum(1 for t in _WORD_RE.findall(q.lower()) if t in _NEG_WORDS)
    e_neg = sum(1 for t in _WORD_RE.findall(ev.lower()) if t in _NEG_WORDS)
    neg_mismatch = 1.0 if ((q_neg > 0) != (e_neg > 0)) else 0.0
    neg_density = min(1.0, e_neg / 3.0)

    qn = set(_NUM_RE.findall(q))
    en = set(_NUM_RE.findall(ev))
    num_match = len(qn & en) / max(1, len(qn)) if qn else 0.5
    num_mismatch = 1.0 if (qn and en and not (qn & en)) else 0.0

    len_ratio = min(1.0, len(et) / max(1, len(qt) * 3))
    return np.array(
        [overlap, jaccard, bi_overlap, neg_mismatch, neg_density, num_match, num_mismatch, len_ratio],
        dtype=np.float32,
    )


def _softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - np.max(x, axis=-1, keepdims=True))
    return e / np.sum(e, axis=-1, keepdims=True)


def fit_soft_softmax(
    X: np.ndarray,
    probs_y: np.ndarray,
    *,
    reg: float = 4e-4,
    steps: int = 700,
    lr: float = 1.8,
) -> tuple[np.ndarray, np.ndarray]:
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


def main() -> None:
    _load_env()
    if not os.getenv("TYPESAFE_API_KEY"):
        raise SystemExit("TYPESAFE_API_KEY not found")

    print("1. Downloading public MultiNLI train (100) + unseen benchmark (100)...")
    nli_train = fetch_multinli(offset=0, length=100)
    nli_bench = fetch_multinli(offset=100, length=100)
    distill_inputs = nli_train + market_seed_rows()

    cache_path = DOLY_ROOT / "data" / "distill" / "oracle_s1_jev.jsonl"
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"2. Distilling {len(distill_inputs)} examples with live TypeSafe Jev...")
    client = TypeSafeClient()
    t0 = time.perf_counter()
    distilled: list[dict] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = [pool.submit(distill_one, client, r) for r in distill_inputs]
        for fut in as_completed(futs):
            try:
                distilled.append(fut.result())
            except Exception as exc:
                print(f"  [warn] Jev call failed: {exc}", file=sys.stderr)
    distill_s = time.perf_counter() - t0
    cache_path.write_text("\n".join(json.dumps(r) for r in distilled) + "\n")
    print(f"   Distilled {len(distilled)}/{len(distill_inputs)} in {distill_s:.1f}s -> {cache_path.name}")

    # Check Jev's own accuracy on the 100 MultiNLI train rows (sanity check)
    jev_nli = [r for r in distilled if r["source"] == "multi_nli"]
    jev_acc = sum(int(np.argmax(r["teacher_probs"]) == r["gold"]) for r in jev_nli) / max(1, len(jev_nli))
    print(f"   Jev teacher 3-class accuracy on MultiNLI-100: {jev_acc:.3f}")

    # 3. Train pure-NumPy oracle-s1 student on Jev soft probabilities (cross-features + TF-IDF)
    tr_txt = [f"Q: {r['question']} | EVIDENCE: {r['evidence']}" for r in distilled]
    tr_probs = np.array([r["teacher_probs"] for r in distilled], dtype=np.float32)

    vw = TfidfVectorizer(ngram_range=(1, 2), max_features=3500, sublinear_tf=True, min_df=1)
    vc = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), max_features=3500, sublinear_tf=True, min_df=2)
    X_tr_tf = np.hstack([vw.fit_transform(tr_txt).astype(np.float32).toarray(), vc.fit_transform(tr_txt).astype(np.float32).toarray()])
    X_tr_cf = np.vstack([cross_features(r["question"], r["evidence"]) for r in distilled])
    X_tr = np.hstack([X_tr_cf, X_tr_tf])
    W, b = fit_soft_softmax(X_tr, tr_probs, reg=1e-3, steps=900, lr=2.0)

    out_dir = DOLY_ROOT / "app" / "models" / "oracle_s1"
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "vocab_word": {k: int(v) for k, v in vw.vocabulary_.items()},
        "idf_word": vw.idf_.astype(np.float16).tolist(),
        "vocab_char": {k: int(v) for k, v in vc.vocabulary_.items()},
        "idf_char": vc.idf_.astype(np.float16).tolist(),
        "cross_features": 8,
        "labels": LABELS,
    }
    (out_dir / "meta.json").write_text(json.dumps(meta))
    np.savez_compressed(out_dir / "weights.npz", W=W.astype(np.float16), b=b.astype(np.float16))
    total_bytes = (out_dir / "meta.json").stat().st_size + (out_dir / "weights.npz").stat().st_size

    # 4. Benchmark on 100 unseen public MultiNLI rows
    be_txt = [f"Q: {r['question']} | EVIDENCE: {r['evidence']}" for r in nli_bench]
    be_gold = np.array([r["gold"] for r in nli_bench], dtype=np.int64)
    X_be_tf = np.hstack([vw.transform(be_txt).astype(np.float32).toarray(), vc.transform(be_txt).astype(np.float32).toarray()])
    X_be_cf = np.vstack([cross_features(r["question"], r["evidence"]) for r in nli_bench])
    X_be = np.hstack([X_be_cf, X_be_tf])
    t_inf0 = time.perf_counter()
    p_be = _softmax(X_be @ W.astype(np.float16).astype(np.float32) + b.astype(np.float16).astype(np.float32))
    inf_ms = (time.perf_counter() - t_inf0) * 1000 / len(nli_bench)
    preds = np.argmax(p_be, axis=1)
    acc_3 = float(np.mean(preds == be_gold))

    print("\n=== BENCHMARK RESULTS (100 unseen MultiNLI validation rows) ===")
    print(f"Artifact size : {total_bytes / 1024:.1f} KB")
    print(f"Inference     : {inf_ms:.3f} ms/sample")
    print(f"3-class acc   : {acc_3:.3f} ({int(acc_3 * len(nli_bench))}/{len(nli_bench)})")
    for idx, lbl in enumerate(LABELS):
        mask = be_gold == idx
        if mask.any():
            cls_acc = float(np.mean(preds[mask] == idx))
            print(f"  {lbl:13s}: {cls_acc:.3f} ({int(np.sum(preds[mask] == idx))}/{int(np.sum(mask))})")


if __name__ == "__main__":
    main()
