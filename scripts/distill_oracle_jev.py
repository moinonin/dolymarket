"""Pull historical Polymarket markets + hard negatives and distill Jev (`jev-latest`) soft labels."""

from __future__ import annotations

import json
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List

import httpx
from dotenv import load_dotenv

DOLY_ROOT = Path(__file__).resolve().parents[1]
GITHERI_ROOT = DOLY_ROOT.parent / "ai" / "githeri"
sys.path.insert(0, str(GITHERI_ROOT / "src"))

from githeri.core.system_one import SystemOneClient, choice, noul  # noqa: E402

ORACLE_QUESTIONS: Dict[str, Dict[str, Any]] = {
    "has_authoritative_source": noul(
        "Does the market specify an authoritative, verifiable resolution source (e.g. official agency, exchange, box score, URL, or named feed)?",
        "Names a concrete authoritative data source, official announcement, or verifiable oracle.",
        "No verifiable resolution source is cited.",
    ),
    "has_unambiguous_predicate": noul(
        "Does the market define an unambiguous binary or numeric resolution predicate (exact win/loss or threshold)?",
        "Clear objective condition determining YES vs NO (or exact winner).",
        "Predicate is vague, open to interpretation, or lacks a clear threshold.",
    ),
    "has_explicit_deadline": noul(
        "Does the market state an explicit resolution date, deadline, or observation window?",
        "Contains a specific date, time, event end, or deadline.",
        "No clear deadline or expiration timeframe.",
    ),
    "has_subjective_ambiguity": noul(
        "Does the market rely on subjective judgment, vibes, 'at my discretion', or unmeasurable loopholes?",
        "Contains subjective wording, weasel words, or creator discretion.",
        "Objective and free of subjective discretion.",
    ),
    "is_resolvable_market": noul(
        "Overall, is this prediction market clear, objective, and safely resolvable without dispute?",
        "Clear question + objective criteria + verifiable source + deadline.",
        "Underspecified, subjective, missing source/deadline, or unresolvable.",
    ),
    "category": choice(
        "What is the primary category of this prediction market?",
        {
            "Crypto": "Cryptocurrencies, Bitcoin, Ethereum, DeFi, tokens, on-chain prices.",
            "Macro": "Central banks, Fed rates, inflation, GDP, stocks, commodities, economics.",
            "Politics": "Elections, legislation, government leaders, geopolitics, courts.",
            "Sports": "Leagues, matches, tournaments, championships, athletes.",
            "Tech": "AI models, software launches, tech companies, science, space.",
            "PopCulture": "Movies, music, awards, social media, celebrities.",
            "Other": "Anything outside the categories above.",
        },
    ),
}


def fetch_polymarket_markets(target: int = 550) -> List[Dict[str, Any]]:
    markets: List[Dict[str, Any]] = []
    seen_q: set[str] = set()
    for closed in ("true", "false"):
        offset = 0
        while len(markets) < target:
            r = httpx.get(
                "https://gamma-api.polymarket.com/markets",
                params={"limit": 100, "offset": offset, "closed": closed},
                timeout=15.0,
            )
            if r.status_code != 200:
                break
            batch = r.json()
            if not batch:
                break
            for m in batch:
                q = (m.get("question") or "").strip()
                desc = (m.get("description") or "").strip()
                if not q or len(desc) < 25 or q in seen_q:
                    continue
                seen_q.add(q)
                markets.append({
                    "id": f"poly_{m.get('id')}",
                    "source": "polymarket",
                    "question": q,
                    "resolution_criteria": desc,
                    "end_date": m.get("endDate") or "",
                    "oracle_feed": m.get("resolutionSource") or "",
                })
                if len(markets) >= target:
                    break
            offset += 100
            if offset >= 600:
                break
    return markets


def generate_bad_markets(n: int = 150, seed: int = 42) -> List[Dict[str, Any]]:
    rng = random.Random(seed)
    subjects = ["Bitcoin", "the Fed", "Apple stock", "NVIDIA", "Ethereum", "the Lakers", "OpenAI", "Taylor Swift"]
    bad: List[Dict[str, Any]] = []
    for i in range(n):
        subj = subjects[i % len(subjects)]
        kind = i % 4
        if kind == 0:
            q = f"Will {subj} do really well soon?"
            desc = "Resolves YES if vibes are good and most people think it went well. Creator discretion applies."
        elif kind == 1:
            q = f"Will {subj} hit an all-time high?"
            desc = "Resolves YES if price goes up. No specific exchange or deadline needed, TBD."
        elif kind == 2:
            q = f"Is {subj} overrated in 2026?"
            desc = "Subjective market based on community consensus and maybe Twitter polls."
        else:
            q = f"Will {subj} announce something big?"
            desc = "Resolves YES if a major announcement happens, probably. Source: internet."
        bad.append({
            "id": f"bad_mkt_{i:03d}",
            "source": "synthetic_bad_market",
            "question": f"{q} (#{i})",
            "resolution_criteria": desc,
            "end_date": "",
            "oracle_feed": "",
        })
    rng.shuffle(bad)
    return bad


def label_market(item: Dict[str, Any], client: SystemOneClient) -> Dict[str, Any] | None:
    state = (
        f"Question: {item['question']}\n"
        f"Resolution Criteria: {item['resolution_criteria']}\n"
        f"End Date: {item['end_date'] or 'unspecified'}\n"
        f"Oracle Feed: {item['oracle_feed'] or 'unspecified'}"
    )
    res = client.query(state=state, questions=ORACLE_QUESTIONS)
    if not res:
        return None
    ans = res["answers"]
    return {
        **item,
        "state": state,
        "teacher": {
            "has_authoritative_source": float(ans["has_authoritative_source"]["noul"]),
            "has_unambiguous_predicate": float(ans["has_unambiguous_predicate"]["noul"]),
            "has_explicit_deadline": float(ans["has_explicit_deadline"]["noul"]),
            "has_subjective_ambiguity": float(ans["has_subjective_ambiguity"]["noul"]),
            "is_resolvable_market": float(ans["is_resolvable_market"]["noul"]),
            "category": ans["category"]["choice"],
            "category_probs": ans["category"].get("probabilities", {}),
        },
    }


def main() -> None:
    load_dotenv(GITHERI_ROOT / ".env")
    load_dotenv(DOLY_ROOT / ".env", override=False)
    client = SystemOneClient(timeout=20.0)
    if not client.is_available():
        print("ERROR: TYPESAFE_API_KEY missing.")
        sys.exit(1)

    poly = fetch_polymarket_markets(550)
    bad = generate_bad_markets(150)
    print(f"Fetched {len(poly)} Polymarket markets + {len(bad)} bad markets")

    rng = random.Random(42)
    rng.shuffle(poly)
    rng.shuffle(bad)

    train_raw = poly[:430] + bad[:120]
    holdout_raw = poly[430:] + bad[120:]

    out_dir = DOLY_ROOT / "data" / "distill"
    out_dir.mkdir(parents=True, exist_ok=True)

    for split, rows in (("train", train_raw), ("holdout", holdout_raw)):
        out_path = out_dir / f"{split}.jsonl"
        t0 = time.perf_counter()
        labeled = []
        with ThreadPoolExecutor(max_workers=10) as pool:
            futs = [pool.submit(label_market, r, client) for r in rows]
            for idx, f in enumerate(as_completed(futs), 1):
                res = f.result()
                if res is not None:
                    labeled.append(res)
                if idx % 100 == 0 or idx == len(rows):
                    print(f"  [{split}] {idx}/{len(rows)} ({len(labeled)} ok, {time.perf_counter()-t0:.1f}s)")
        out_path.write_text("\n".join(json.dumps(r) for r in labeled) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
