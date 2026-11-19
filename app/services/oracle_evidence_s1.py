"""Offline `oracle-s1` evidence verifier: MobileBERT/DeBERTa INT8 ONNX + pure-NumPy fallback.

Supports Kalshi-style declarative resolution rules:
- Rule 1: Declarative `Resolves Yes if ...` claim extraction
- Rule 2: Whitelisted Source Agency domain extraction (`Outcome verified from ...`)
- Rule 3: Default-to-NO on expiration (`no data ... resolve to No`)
- Deterministic numeric threshold guard (`>=`, `>`, `<=`, `<`, `==`)
"""
from __future__ import annotations

import itertools
import json
import math
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import numpy as np

_DOLY_ROOT = Path(__file__).resolve().parents[2]
_MODEL_DIR = Path(__file__).resolve().parents[1] / "models" / "oracle_s1"
_WORD_RE = re.compile(r"(?u)\b\w\w+\b")

# Canonical Source Agency -> allowed registrable domains (Kalshi Rule 2).
_AGENCY_DOMAINS: dict[str, tuple[str, ...]] = {
    "reuters": ("reuters.com",),
    "associated press": ("apnews.com", "ap.org"),
    "bbc": ("bbc.com", "bbc.co.uk"),
    "the wall street journal": ("wsj.com",),
    "wall street journal": ("wsj.com",),
    "bloomberg news": ("bloomberg.com",),
    "bloomberg": ("bloomberg.com",),
    "cnbc": ("cnbc.com",),
    "cbs": ("cbsnews.com", "cbs.com"),
    "nbc": ("nbcnews.com", "nbc.com"),
    "abc": ("abcnews.go.com", "abc.com"),
    "fox news": ("foxnews.com", "foxbusiness.com"),
    "the washington post": ("washingtonpost.com",),
    "washington post": ("washingtonpost.com",),
    "cnn": ("cnn.com",),
    "the new york times": ("nytimes.com",),
    "new york times": ("nytimes.com",),
    "ms now": ("msnbc.com", "msnow.com"),
    "take-two interactive": ("take2games.com", "ir.take2games.com", "rockstargames.com"),
    "federal reserve": ("federalreserve.gov",),
    "bureau of labor statistics": ("bls.gov",),
    "sec": ("sec.gov",),
    "national weather service": ("weather.gov",),
    "coingecko": ("coingecko.com",),
}

_DOMAIN_RE = re.compile(r"\b([a-z0-9-]+(?:\.[a-z0-9-]+)+)\b", re.IGNORECASE)
_NUM_SCALE = {"million": 1e6, "m": 1e6, "billion": 1e9, "b": 1e9, "thousand": 1e3, "k": 1e3}
_SCALED_NUM_RE = re.compile(
    r"\$?(\d+(?:,\d+)*(?:\.\d+)?)\s*(million|billion|thousand|[mbk])?(?:%|bps)?",
    re.IGNORECASE,
)

_ONNX_PRESETS: dict[str, dict[str, str]] = {
    "mobilebert": {
        "dir_name": "mobilebert-uncased-mnli",
        "repo": "Xenova/mobilebert-uncased-mnli",
        "onnx_file": "model_int8.onnx",
        "onnx_remote": "onnx/model_int8.onnx",
    },
    "deberta": {
        "dir_name": "nli-deberta-v3-xsmall",
        "repo": "Xenova/nli-deberta-v3-xsmall",
        "onnx_file": "model_quantized.onnx",
        "onnx_remote": "onnx/model_quantized.onnx",
    },
}


def parse_kalshi_rules(resolution_criteria: str | None) -> dict[str, Any]:
    """Parse Kalshi-style resolution criteria into structured contract clauses."""
    raw = (resolution_criteria or "").strip()
    if not raw:
        return {
            "resolves_yes_if": None,
            "allowed_domains": [],
            "no_data_resolves_no": False,
        }

    resolves_yes_if: str | None = None
    m_yes = re.search(r"resolves\s+yes\s+if\s+(.+?)(?:\n|$)", raw, flags=re.IGNORECASE)
    if m_yes:
        resolves_yes_if = m_yes.group(1).strip()

    allowed: set[str] = set()
    m_src = re.search(
        r"(?:outcome\s+verified\s+from|source\s+agenc(?:y|ies)\s*:?)\s*(.+?)(?:\n|$)",
        raw,
        flags=re.IGNORECASE,
    )
    if m_src:
        src_clause = m_src.group(1)
        src_low = src_clause.lower()
        for agency, domains in _AGENCY_DOMAINS.items():
            if agency in src_low:
                allowed.update(domains)
        for dom in _DOMAIN_RE.findall(src_clause):
            d = dom.lower().removeprefix("www.")
            if "." in d and not d.endswith((".inc", ".corp")):
                allowed.add(d)

    no_data_no = bool(
        re.search(r"no\s+data.{0,120}resolve(?:s)?\s+(?:to\s+)?no", raw, flags=re.IGNORECASE | re.DOTALL)
    )
    return {
        "resolves_yes_if": resolves_yes_if,
        "allowed_domains": sorted(allowed),
        "no_data_resolves_no": no_data_no,
    }


def is_allowed_source_url(source_url: str, allowed_domains: list[str]) -> bool:
    """Check whether source_url hostname matches any whitelisted domain (or subdomain)."""
    if not allowed_domains:
        return True
    host = (urlparse(source_url).hostname or "").lower().rstrip(".")
    if not host:
        return False
    for dom in allowed_domains:
        d = dom.lower().lstrip(".")
        if host == d or host.endswith("." + d):
            return True
    return False


_MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|November|December"
)
_DEADLINE_RE = re.compile(
    rf"\b(?:before|by|prior\s+to|on\s+or\s+before)\s+"
    rf"(?:(?:{_MONTHS})\s+\d{{1,2}},?\s+\d{{4}}|\d{{4}}-\d{{2}}-\d{{2}}|\d{{4}}|"
    rf"Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|tomorrow|tonight|today)\b",
    re.IGNORECASE,
)
_THRESH_PHRASE_RE = re.compile(
    r"\b(?:at\s+least|at\s+most|more\s+than|less\s+than|above|below|over|under|exceed(?:s|ed)?|reached?)\s+"
    r"\$?\d+(?:,\d+)*(?:\.\d+)?\s*(?:million|billion|thousand|[mbk]|%|bps)?\b",
    re.IGNORECASE,
)


def to_declarative_claim(
    question: str,
    resolution_criteria: str | None = None,
    *,
    strip_numeric_threshold: bool = False,
) -> str:
    """Convert market question or Kalshi rule into a clean declarative NLI hypothesis.

    Strips legal parentheticals and deadline clauses enforced deterministically by code;
    when `strip_numeric_threshold=True`, code enforces the threshold math so NLI focuses
    strictly on the underlying semantic event.
    """
    parsed = parse_kalshi_rules(resolution_criteria)
    if parsed["resolves_yes_if"]:
        s = parsed["resolves_yes_if"]
    else:
        s = (question or "").strip().rstrip("?")
        s = re.sub(r"^(Will|Does|Did|Has|Have|Can|Is|Are)\s+", "", s, flags=re.IGNORECASE)

    s = re.sub(r"\([^)]*\)", "", s)
    s = re.sub(r",?\s*\b(?:Inc|LLC|Corp|Ltd)\.?", "", s, flags=re.IGNORECASE)
    s = _DEADLINE_RE.sub("", s)
    if strip_numeric_threshold:
        s = _THRESH_PHRASE_RE.sub("", s)
    s = re.sub(r"\s+", " ", s).strip().rstrip(".,;:")
    return s + "."


def extract_scaled_numbers(text: str) -> list[float]:
    """Extract numeric values with optional scale suffixes (million, billion, k, M, B)."""
    vals: list[float] = []
    for num_s, unit in _SCALED_NUM_RE.findall(text or ""):
        try:
            v = float(num_s.replace(",", ""))
        except ValueError:
            continue
        if unit:
            v *= _NUM_SCALE.get(unit.lower(), 1.0)
        vals.append(v)
    return vals


def check_numeric_threshold(
    evidence_text: str,
    comparator: str | None,
    threshold: float | None,
) -> bool:
    """Deterministic numeric guard for threshold markets (e.g. >= 36 million)."""
    if comparator is None or threshold is None:
        return True
    nums = extract_scaled_numbers(evidence_text)
    if not nums:
        return False
    target = float(threshold)
    if not (1990 <= target <= 2035):
        non_years = [n for n in nums if not (1990 <= n <= 2035)]
        if non_years:
            nums = non_years
    op = comparator.strip()
    if op == ">=":
        return any(n >= target for n in nums)
    if op == ">":
        return any(n > target for n in nums)
    if op == "<=":
        return any(n <= target for n in nums)
    if op == "<":
        return any(n < target for n in nums)
    if op in ("==", "="):
        return any(abs(n - target) <= max(1e-6, abs(target) * 1e-4) for n in nums)
    return True


def _resolve_onnx_dir(preset_key: str) -> Path:
    preset = _ONNX_PRESETS.get(preset_key, _ONNX_PRESETS["mobilebert"])
    env_dir = os.environ.get("ORACLE_S1_CACHE_DIR", "").strip()
    if env_dir:
        return Path(env_dir) / preset["dir_name"]
    local_dir = _DOLY_ROOT / "data" / "models" / preset["dir_name"]
    if (local_dir / preset["onnx_file"]).exists():
        return local_dir
    return Path("/tmp/dolymarket_oracle_s1") / preset["dir_name"]


def _ensure_onnx_files(preset_key: str) -> Path | None:
    preset = _ONNX_PRESETS.get(preset_key, _ONNX_PRESETS["mobilebert"])
    model_dir = _resolve_onnx_dir(preset_key)
    needed = {
        "config.json": "config.json",
        "tokenizer.json": "tokenizer.json",
        preset["onnx_file"]: preset["onnx_remote"],
    }
    if all((model_dir / fname).exists() for fname in needed):
        return model_dir
    if os.environ.get("ORACLE_S1_AUTO_DOWNLOAD", "0").strip() != "1":
        return None
    try:
        import httpx

        model_dir.mkdir(parents=True, exist_ok=True)
        base = f"https://huggingface.co/{preset['repo']}/resolve/main"
        for fname, remote in needed.items():
            dst = model_dir / fname
            if dst.exists():
                continue
            with httpx.stream("GET", f"{base}/{remote}", follow_redirects=True, timeout=120.0) as r:
                r.raise_for_status()
                with dst.open("wb") as f:
                    for chunk in r.iter_bytes(chunk_size=1 << 20):
                        f.write(chunk)
        return model_dir
    except Exception:  # noqa: BLE001
        return None


@lru_cache(maxsize=2)
def _load_onnx_nli(preset_key: str) -> tuple[Any, Any, list[str], list[int], str] | None:
    """Load quantized ONNX cross-encoder (MobileBERT 26MB or DeBERTa-xsmall 87MB)."""
    if os.environ.get("ORACLE_S1_DISABLE_ONNX", "0").strip() == "1":
        return None
    try:
        import onnxruntime as ort
        from tokenizers import Tokenizer
    except ImportError:
        return None

    model_dir = _ensure_onnx_files(preset_key)
    if model_dir is None:
        return None
    preset = _ONNX_PRESETS.get(preset_key, _ONNX_PRESETS["mobilebert"])
    try:
        cfg = json.loads((model_dir / "config.json").read_text())
        id2lbl = {int(k): v.lower() for k, v in cfg["id2label"].items()}
        idx_ent = next(k for k, v in id2lbl.items() if "entail" in v)
        idx_con = next(k for k, v in id2lbl.items() if "contra" in v)
        idx_neu = next(k for k, v in id2lbl.items() if "neut" in v)
        remap = [idx_ent, idx_con, idx_neu]

        tok = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        tok.enable_truncation(max_length=256)
        sess = ort.InferenceSession(
            str(model_dir / preset["onnx_file"]),
            providers=["CPUExecutionProvider"],
        )
        in_names = [i.name for i in sess.get_inputs()]
        return sess, tok, in_names, remap, f"oracle_s1_onnx_{preset_key}"
    except Exception:  # noqa: BLE001
        return None


def _predict_onnx_nli(
    hypothesis: str,
    evidence_text: str,
) -> tuple[np.ndarray, str] | None:
    preset_key = os.environ.get("ORACLE_S1_ONNX_MODEL", "mobilebert").strip().lower()
    loaded = _load_onnx_nli(preset_key)
    if loaded is None:
        return None
    sess, tok, in_names, remap, mode = loaded
    enc = tok.encode(evidence_text[:3000], hypothesis)
    feed: dict[str, np.ndarray] = {
        "input_ids": np.array([enc.ids], dtype=np.int64),
        "attention_mask": np.array([enc.attention_mask], dtype=np.int64),
    }
    if "token_type_ids" in in_names:
        feed["token_type_ids"] = np.array([enc.type_ids], dtype=np.int64)
    logits = sess.run(None, feed)[0][0]
    e = np.exp(logits - np.max(logits))
    p = e / np.sum(e)
    probs = np.array([p[remap[0]], p[remap[1]], p[remap[2]]], dtype=np.float32)
    return probs, mode


# --- Pure-NumPy fallback (<200 KB) ---
_STOPWORDS = frozenset({"the", "a", "an", "is", "are", "was", "were", "be", "been", "to", "of", "in", "on", "at", "for", "and", "or", "by", "with", "that", "this", "it", "will", "would", "can", "could", "has", "have", "had", "do", "does", "did"})
_NEG_WORDS = frozenset({"not", "no", "never", "neither", "nor", "none", "nothing", "nowhere", "without", "hardly", "barely", "scarcely", "denied", "rejected", "failed", "cancelled", "canceled", "postponed", "unchanged", "paused", "below", "less", "lower", "unlikely", "refused", "blocked", "stopped", "dropped"})
_CF_WORD_RE = re.compile(r"[a-z0-9]+")
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def _cross_features(q: str, ev: str) -> np.ndarray:
    qt = [t for t in _CF_WORD_RE.findall(q.lower()) if t not in _STOPWORDS]
    et = [t for t in _CF_WORD_RE.findall(ev.lower()) if t not in _STOPWORDS]
    qs, es = set(qt), set(et)
    overlap = len(qs & es) / max(1, len(qs))
    jaccard = len(qs & es) / max(1, len(qs | es))
    q_bi = set(itertools.pairwise(qt))
    e_bi = set(itertools.pairwise(et))
    bi_overlap = len(q_bi & e_bi) / max(1, len(q_bi))
    q_neg = sum(1 for t in _CF_WORD_RE.findall(q.lower()) if t in _NEG_WORDS)
    e_neg = sum(1 for t in _CF_WORD_RE.findall(ev.lower()) if t in _NEG_WORDS)
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


def _tf_vec(counts: dict[int, int], idf: np.ndarray) -> np.ndarray:
    vec = np.zeros(len(idf), dtype=np.float32)
    if not counts:
        return vec
    for idx, c in counts.items():
        vec[idx] = (1.0 + math.log(c)) * idf[idx]
    norm = float(np.linalg.norm(vec))
    if norm > 0:
        vec /= norm
    return vec


def _featurize(text: str, meta: dict[str, Any]) -> np.ndarray:
    low = text.lower()
    tokens = _WORD_RE.findall(low)
    vw: dict[str, int] = meta["vocab_word"]
    iw = np.array(meta["idf_word"], dtype=np.float32)
    w_counts: dict[int, int] = {}
    for n in (1, 2):
        for i in range(len(tokens) - n + 1):
            gram = " ".join(tokens[i : i + n])
            idx = vw.get(gram)
            if idx is not None:
                w_counts[idx] = w_counts.get(idx, 0) + 1

    vc: dict[str, int] = meta["vocab_char"]
    ic = np.array(meta["idf_char"], dtype=np.float32)
    c_counts: dict[int, int] = {}
    for w in tokens:
        padded = f" {w} "
        for n in (3, 4, 5):
            for i in range(len(padded) - n + 1):
                gram = padded[i : i + n]
                idx = vc.get(gram)
                if idx is not None:
                    c_counts[idx] = c_counts.get(idx, 0) + 1

    return np.hstack([_tf_vec(w_counts, iw), _tf_vec(c_counts, ic)])


@lru_cache(maxsize=1)
def _load_oracle_s1() -> tuple[dict[str, Any], np.ndarray, np.ndarray] | None:
    meta_path = _MODEL_DIR / "meta.json"
    weights_path = _MODEL_DIR / "weights.npz"
    if not meta_path.exists() or not weights_path.exists():
        return None
    meta = json.loads(meta_path.read_text())
    npz = np.load(weights_path)
    return meta, npz["W"].astype(np.float32), npz["b"].astype(np.float32)


def predict_evidence_s1(
    question: str,
    proposed_outcome: str,
    evidence_text: str,
    *,
    resolution_criteria: str | None = None,
    oracle_threshold: float | None = None,
    oracle_comparator: str | None = None,
) -> dict[str, Any] | None:
    """Predict verdict + calibrated probability using local `oracle-s1` (ONNX -> NumPy)."""
    if not (evidence_text or "").strip():
        return None

    labels = ["YES_EVIDENCE", "NO_EVIDENCE", "INCONCLUSIVE"]
    has_num_guard = oracle_threshold is not None and oracle_comparator is not None
    hypothesis = to_declarative_claim(
        question,
        resolution_criteria,
        strip_numeric_threshold=has_num_guard,
    )
    onnx_out = _predict_onnx_nli(hypothesis, evidence_text)
    if onnx_out is not None:
        probs, mode = onnx_out
    else:
        loaded = _load_oracle_s1()
        if loaded is None:
            return None
        meta, W, b = loaded
        labels = meta["labels"]
        prompt = f"Q: {question} | EVIDENCE: {evidence_text}"
        x_tf = _featurize(prompt, meta)
        x = np.hstack([_cross_features(question, evidence_text), x_tf]) if meta.get("cross_features") else x_tf
        logits = x @ W + b
        e = np.exp(logits - np.max(logits))
        probs = e / np.sum(e)
        mode = "oracle_s1"

    numeric_ok = check_numeric_threshold(evidence_text, oracle_comparator, oracle_threshold)
    best_idx = int(np.argmax(probs))
    ev_label = labels[best_idx]
    conf = round(float(probs[best_idx]), 3)

    # Deterministic numeric guard blocks false-positive YES when threshold is unmet.
    if ev_label == "YES_EVIDENCE" and not numeric_ok:
        ev_label = "NO_EVIDENCE"
        conf = round(max(0.85, float(probs[1])), 3)

    prop_yes = (proposed_outcome or "").strip().upper() in ("YES", "TRUE", "1")
    if ev_label == "INCONCLUSIVE":
        verdict = "INCONCLUSIVE"
    elif (ev_label == "YES_EVIDENCE" and prop_yes) or (ev_label == "NO_EVIDENCE" and not prop_yes):
        verdict = "SUPPORTS"
    else:
        verdict = "CONTRADICTS"

    return {
        "verdict": verdict,
        "confidence": conf,
        "evidence_label": ev_label,
        "numeric_ok": numeric_ok,
        "hypothesis": hypothesis,
        "probs": {lbl: round(float(probs[i]), 3) for i, lbl in enumerate(labels)},
        "mode": mode,
    }
