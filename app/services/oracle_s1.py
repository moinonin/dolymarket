"""Pure-NumPy runtime loader for `dolymarket-s1` (<1 MB distilled oracle clarity model)."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None  # type: ignore[assignment]

_MODEL_DIR = Path(__file__).resolve().parent.parent / "models" / "dolymarket_s1"
_TOKEN_RX = re.compile(r"(?u)\b\w\w+\b")


def _sigmoid(x: float) -> float:
    x = max(-30.0, min(30.0, float(x)))
    return 1.0 / (1.0 + math.exp(-x))


class OracleDecisionModel:
    """Self-contained <1 MB distilled clarity & category model for prediction markets."""

    def __init__(self, model_dir: Path = _MODEL_DIR) -> None:
        self.model_dir = Path(model_dir)
        self._loaded = False
        self._meta: Dict[str, Any] = {}
        self._weights: Dict[str, Any] = {}

    def is_available(self) -> bool:
        return (
            np is not None
            and (self.model_dir / "meta.json").is_file()
            and (self.model_dir / "weights.npz").is_file()
        )

    def _ensure_loaded(self) -> bool:
        if self._loaded:
            return True
        if not self.is_available():
            return False
        self._meta = json.loads((self.model_dir / "meta.json").read_text(encoding="utf-8"))
        with np.load(self.model_dir / "weights.npz") as z:
            self._weights = {k: z[k].astype(np.float32) for k in z.files}
        self._loaded = True
        return True

    def _vectorize(self, ngrams: List[str], vocab: Dict[str, int], idf: List[float]) -> "np.ndarray":
        vec = np.zeros(len(idf), dtype=np.float32)
        for term, cnt in Counter(ngrams).items():
            idx = vocab.get(term)
            if idx is not None:
                vec[idx] = (1.0 + math.log(cnt)) * idf[idx]
        norm = float(np.linalg.norm(vec))
        if norm > 0.0:
            vec /= norm
        return vec

    def _featurize(self, text: str) -> "np.ndarray":
        tokens = _TOKEN_RX.findall(text.lower())
        w_ngrams = [" ".join(tokens[i : i + n]) for n in (1, 2, 3) for i in range(len(tokens) - n + 1)]
        c_ngrams: List[str] = []
        for tok in tokens:
            padded = f" {tok} "
            for n in (3, 4, 5):
                if len(padded) >= n:
                    for i in range(len(padded) - n + 1):
                        c_ngrams.append(padded[i : i + n])
        xw = self._vectorize(w_ngrams, self._meta["vocab_word"], self._meta["idf_word"])
        xc = self._vectorize(c_ngrams, self._meta["vocab_char"], self._meta["idf_char"])
        return np.concatenate([xw, xc])

    def predict(
        self,
        resolution_criteria: str,
        *,
        question: Optional[str] = None,
        end_date: Any = None,
        oracle_feed: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        if not self._ensure_loaded():
            return None

        state = (
            f"Question: {(question or '').strip()}\n"
            f"Resolution Criteria: {(resolution_criteria or '').strip()}\n"
            f"End Date: {end_date if end_date is not None else 'unspecified'}\n"
            f"Oracle Feed: {(oracle_feed or '').strip() or 'unspecified'}"
        )
        x = self._featurize(state)

        noul_keys: List[str] = self._meta["noul_keys"]
        logits = self._weights["W_noul"] @ x + self._weights["b_noul"]
        probs = {k: round(_sigmoid(float(logits[i])), 3) for i, k in enumerate(noul_keys)}

        cats: List[str] = self._meta["categories"]
        cat_logits = x @ self._weights["W_cat"] + self._weights["b_cat"]
        cat_logits = cat_logits - np.max(cat_logits)
        cat_exp = np.exp(cat_logits)
        cat_probs = cat_exp / np.sum(cat_exp)
        category = cats[int(np.argmax(cat_probs))]

        return {**probs, "category": category, "engine": "dolymarket_s1"}


_SHARED: Optional[OracleDecisionModel] = None


def get_oracle_decision_model() -> OracleDecisionModel:
    global _SHARED
    if _SHARED is None:
        _SHARED = OracleDecisionModel()
    return _SHARED
