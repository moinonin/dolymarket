"""System One evidence verifier for bond-free qualitative market resolution.

Code fetches the cited primary source URL (with strict SSRF guards); System One
(`Jev` via TypeSafe when ``TYPESAFE_API_KEY`` is configured, or hermetic local
entailment fallback offline) judges whether the evidence supports, contradicts,
or is inconclusive for the proposed resolution outcome.
"""
from __future__ import annotations

import ipaddress
import os
import re
import socket
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _validate_public_http_url(url: str) -> str:
    """Ensure source_url is public HTTP(S) and does not target private/loopback IPs."""
    raw = (url or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise HTTPException(status_code=422, detail="source_url must be a valid http(s) URL")
    host = parsed.hostname.lower()
    if host in ("localhost", "localhost.localdomain"):
        raise HTTPException(status_code=422, detail="source_url cannot target localhost")
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise HTTPException(status_code=422, detail="source_url cannot target private IP")
    except ValueError:
        try:
            for info in socket.getaddrinfo(host, None):
                ip = ipaddress.ip_address(info[4][0])
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                    raise HTTPException(status_code=422, detail="source_url resolves to private IP")
        except HTTPException:
            raise
        except socket.gaierror:
            pass
    return raw


async def fetch_source_text(source_url: str, *, max_chars: int = 4000) -> str:
    """Fetch and strip HTML from a public source URL."""
    url = _validate_public_http_url(source_url)
    async with httpx.AsyncClient(timeout=8.0, follow_redirects=False) as client:
        resp = await client.get(url, headers={"User-Agent": "dolymarket-oracle-verifier/1.0"})
        if resp.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"Evidence URL returned HTTP {resp.status_code}")
        text = _TAG_RE.sub(" ", resp.text)
        return _WS_RE.sub(" ", text).strip()[:max_chars]


def _local_entailment(
    question: str,
    proposed_outcome: str,
    evidence_text: str,
) -> dict[str, Any]:
    """Hermetic deterministic fallback when TYPESAFE_API_KEY is absent."""
    ev = (evidence_text or "").lower()
    prop = (proposed_outcome or "").strip().upper()
    if not ev.strip():
        return {"verdict": "INCONCLUSIVE", "confidence": 0.0, "mode": "local_entailment"}

    pos_cues = ("confirmed", "approved", "passed", "signed", "enacted", "completed", "launched", "cut by", "above")
    neg_cues = ("rejected", "failed", "cancelled", "canceled", "denied", "did not", "never", "below", "postponed")

    pos_hits = sum(1 for c in pos_cues if c in ev)
    neg_hits = sum(1 for c in neg_cues if c in ev)

    if pos_hits == 0 and neg_hits == 0:
        return {"verdict": "INCONCLUSIVE", "confidence": 0.45, "mode": "local_entailment"}

    ev_is_yes = pos_hits > neg_hits
    ev_is_no = neg_hits > pos_hits
    if not (ev_is_yes or ev_is_no):
        return {"verdict": "INCONCLUSIVE", "confidence": 0.5, "mode": "local_entailment"}

    proposed_yes = prop in ("YES", "TRUE", "1")
    agrees = (proposed_yes and ev_is_yes) or ((not proposed_yes) and ev_is_no)
    margin = abs(pos_hits - neg_hits)
    conf = min(0.95, 0.72 + 0.08 * margin)
    return {
        "verdict": "SUPPORTS" if agrees else "CONTRADICTS",
        "confidence": round(conf, 2),
        "mode": "local_entailment",
    }


async def verify_resolution_evidence(
    question: str,
    proposed_outcome: str,
    *,
    source_url: str | None = None,
    evidence_text: str | None = None,
) -> dict[str, Any]:
    """Verify whether cited evidence supports or contradicts a proposed resolution."""
    text = (evidence_text or "").strip()
    if not text and source_url:
        text = await fetch_source_text(source_url)

    api_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if api_key and text:
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                resp = await client.post(
                    os.environ.get("TYPESAFE_API_URL", "https://api.typesafe.ai/v1/judge"),
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "model": "jev",
                        "question": (
                            f"Does this evidence support resolving '{question}' as '{proposed_outcome}'? "
                            "Answer SUPPORTS, CONTRADICTS, or INCONCLUSIVE."
                        ),
                        "context": text[:3500],
                        "choices": ["SUPPORTS", "CONTRADICTS", "INCONCLUSIVE"],
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    verdict = str(data.get("choice") or data.get("answer") or "INCONCLUSIVE").upper()
                    conf = float(data.get("confidence", 0.5))
                    if verdict in ("SUPPORTS", "CONTRADICTS", "INCONCLUSIVE"):
                        return {"verdict": verdict, "confidence": conf, "mode": "jev"}
        except Exception:
            pass

    return _local_entailment(question, proposed_outcome, text)
