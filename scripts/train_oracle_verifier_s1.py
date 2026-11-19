"""Train <1 MB pure-NumPy `oracle-s1` evidence verification student.

Predicts ["SUPPORTS", "CONTRADICTS", "INCONCLUSIVE"] for:
    (question, proposed_outcome, evidence_text)
"""
from __future__ import annotations

import json
import random
import time
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

DOLY_ROOT = Path(__file__).resolve().parents[1]
LABELS = ["YES_EVIDENCE", "NO_EVIDENCE", "INCONCLUSIVE"]


def _softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - np.max(x, axis=-1, keepdims=True))
    return e / np.sum(e, axis=-1, keepdims=True)


def fit_softmax(
    X: np.ndarray,
    y_idx: np.ndarray,
    *,
    num_classes: int = 3,
    reg: float = 3e-4,
    steps: int = 600,
    lr: float = 1.8,
) -> tuple[np.ndarray, np.ndarray]:
    n, d = X.shape
    Y = np.eye(num_classes, dtype=np.float32)[y_idx]
    W = np.zeros((d, num_classes), dtype=np.float32)
    b = np.zeros(num_classes, dtype=np.float32)
    for _ in range(steps):
        p = _softmax(X @ W + b)
        err = p - Y
        W -= lr * ((X.T @ err) / n + reg * W)
        b -= lr * np.mean(err, axis=0)
    return W, b


def _build_dataset() -> list[tuple[str, int]]:
    """Build diverse, negation-aware market evidence verification examples."""
    scenarios = [
        # (question, yes_evidence, no_evidence, neutral_evidence)
        (
            "Will the Federal Reserve cut interest rates at the December FOMC meeting?",
            "FOMC statement confirms Federal Reserve cut the federal funds target range by 25 basis points today.",
            "Federal Reserve held rates steady and paused rate cuts at the December FOMC meeting, keeping target unchanged.",
            "Markets await upcoming Federal Reserve minutes as Treasury yields trade flat ahead of Friday data.",
        ),
        (
            "Will US CPI year-over-year print above 3.0% in October?",
            "BLS report shows Consumer Price Index rose 3.2% year-over-year in October, exceeding 3.0%.",
            "BLS October CPI came in at 2.6% year-over-year, below the 3.0% threshold.",
            "Bureau of Labor Statistics scheduled its next methodological update for housing weights next quarter.",
        ),
        (
            "Will Anthropic complete an IPO before 2027?",
            "Anthropic completed its Nasdaq IPO debut today after pricing shares above the marketed range.",
            "Anthropic denied IPO rumors and postponed public listing plans indefinitely.",
            "Anthropic released a new frontier model benchmark and expanded enterprise API capacity.",
        ),
        (
            "Will the Senate pass the bipartisan stablecoin bill before Friday?",
            "The US Senate passed the stablecoin bill by a 68-30 vote and sent it to the White House.",
            "The Senate rejected the stablecoin bill after cloture failed and leadership pulled the measure.",
            "Senators held a procedural hearing on banking committee schedules for next month.",
        ),
        (
            "Will Bitcoin close above $150,000 on Coinbase before September 1?",
            "Bitcoin surged past $152,400 and closed above $150,000 on Coinbase daily settlement.",
            "Bitcoin never traded above $150,000 before September 1 and closed below $118,000.",
            "Bitcoin spot ETF inflows slowed this week as miners upgraded hardware.",
        ),
        (
            "Will the FDA approve the Alzheimer drug candidate this quarter?",
            "FDA granted full approval to the Alzheimer therapy today following Phase 3 review.",
            "FDA issued a Complete Response Letter rejecting the drug application and denying approval.",
            "Biotech conference panelists discussed early-stage neurology biomarkers.",
        ),
        (
            "Will NYC Central Park high temperature exceed 90F on July 4?",
            "NWS Central Park station recorded a daily maximum temperature of 94F on July 4.",
            "NWS Central Park peaked at 81F on July 4, staying well below 90F.",
            "National Weather Service issued routine coastal wind advisories for New England.",
        ),
        (
            "Will the Boston Celtics win the NBA Championship?",
            "Boston Celtics clinched the NBA Finals in Game 6 to win the NBA Championship.",
            "Boston Celtics were eliminated from the playoffs and failed to win the NBA Championship.",
            "NBA announced summer league schedule dates and salary cap projections.",
        ),
        (
            "Will SpaceX launch Starship Flight 8 before March 1?",
            "SpaceX successfully launched Starship Flight 8 from Starbase ahead of March 1.",
            "SpaceX cancelled and scrubbed Starship Flight 8 until late spring after FAA review.",
            "SpaceX unveiled updated spacesuit designs for future orbital missions.",
        ),
        (
            "Will the S&P 500 close above 6,500 on Friday?",
            "S&P 500 finished Friday at 6,540, closing above the 6,500 mark.",
            "S&P 500 fell 1.4% on Friday to close at 6,380, below 6,500.",
            "Wall Street analysts published Q3 sector rotation notes for industrial stocks.",
        ),
    ]

    rows: list[tuple[str, int]] = []
    prefixes = ["", "Official release: ", "Reuters report: ", "SEC / Gov update: ", "Breaking: ", "Press note: "]
    for q, yes_ev, no_ev, neu_ev in scenarios:
        for pref in prefixes:
            rows.append((f"Q: {q} | EVIDENCE: {pref}{yes_ev}", 0))  # YES_EVIDENCE
            rows.append((f"Q: {q} | EVIDENCE: {pref}{no_ev}", 1))   # NO_EVIDENCE
            rows.append((f"Q: {q} | EVIDENCE: {pref}{neu_ev}", 2))  # INCONCLUSIVE

    # Extra hard negation / subtle phrasing pairs
    hard_pairs = [
        ("Q: Will Fed cut rates? | EVIDENCE: Rates were not cut; FOMC kept policy unchanged.", 1),
        ("Q: Will Fed cut rates? | EVIDENCE: FOMC enacted a 25bps rate cut today.", 0),
        ("Q: Will bill pass? | EVIDENCE: Measure was not approved and remains stalled in committee.", 1),
        ("Q: Will bill pass? | EVIDENCE: Bill passed the floor vote and was signed into law.", 0),
        ("Q: Will company IPO? | EVIDENCE: CEO dismissed IPO speculation as premature.", 1),
        ("Q: Will company IPO? | EVIDENCE: Company completed its Nasdaq IPO debut today.", 0),
        ("Q: Will merger close? | EVIDENCE: Regulators blocked the merger and deal was terminated.", 1),
        ("Q: Will merger close? | EVIDENCE: Deal closed after FTC clearance.", 0),
        ("Q: Will merger close? | EVIDENCE: Company hired new VP of marketing.", 2),
        ("Q: Will Anthropic IPO? | EVIDENCE: Anthropic released a new model benchmark.", 2),
    ]
    for _ in range(4):
        rows.extend(hard_pairs)

    random.Random(42).shuffle(rows)
    return rows


def main() -> None:
    rows = _build_dataset()
    split = int(0.8 * len(rows))
    train_rows, hold_rows = rows[:split], rows[split:]

    tr_txt = [r[0] for r in train_rows]
    tr_y = np.array([r[1] for r in train_rows], dtype=np.int64)
    ho_txt = [r[0] for r in hold_rows]
    ho_y = np.array([r[1] for r in hold_rows], dtype=np.int64)

    vw = TfidfVectorizer(ngram_range=(1, 2), max_features=3000, sublinear_tf=True, min_df=1)
    vc = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), max_features=3000, sublinear_tf=True, min_df=2)
    X_tr = np.hstack([vw.fit_transform(tr_txt).astype(np.float32).toarray(), vc.fit_transform(tr_txt).astype(np.float32).toarray()])
    X_ho = np.hstack([vw.transform(ho_txt).astype(np.float32).toarray(), vc.transform(ho_txt).astype(np.float32).toarray()])

    t0 = time.perf_counter()
    W, b = fit_softmax(X_tr, tr_y)
    train_s = time.perf_counter() - t0

    out_dir = DOLY_ROOT / "app" / "models" / "oracle_s1"
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "vocab_word": {k: int(v) for k, v in vw.vocabulary_.items()},
        "idf_word": vw.idf_.astype(np.float16).tolist(),
        "vocab_char": {k: int(v) for k, v in vc.vocabulary_.items()},
        "idf_char": vc.idf_.astype(np.float16).tolist(),
        "labels": LABELS,
    }
    (out_dir / "meta.json").write_text(json.dumps(meta))
    np.savez_compressed(
        out_dir / "weights.npz",
        W=W.astype(np.float16),
        b=b.astype(np.float16),
    )

    p_ho = _softmax(X_ho @ W.astype(np.float16).astype(np.float32) + b.astype(np.float16).astype(np.float32))
    acc = float(np.mean(np.argmax(p_ho, axis=1) == ho_y))
    total_bytes = (out_dir / "meta.json").stat().st_size + (out_dir / "weights.npz").stat().st_size
    print(f"Trained oracle-s1 in {train_s:.2f}s | train={len(train_rows)} holdout={len(hold_rows)}")
    print(f"Holdout accuracy: {acc:.3f} | Artifact size: {total_bytes / 1024:.1f} KB")


if __name__ == "__main__":
    main()
