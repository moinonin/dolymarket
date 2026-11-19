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


_ALLOWED_CONTENT_PREFIXES = (
    "text/",
    "application/json",
    "application/xml",
    "application/xhtml",
)


async def fetch_source_text(
    source_url: str,
    *,
    max_chars: int = 4000,
    max_bytes: int = 65536,
) -> str:
    """Fetch and strip HTML from a public source URL with strict byte + content-type caps."""
    url = _validate_public_http_url(source_url)
    async with httpx.AsyncClient(timeout=8.0, follow_redirects=False) as client:
        async with client.stream(
            "GET",
            url,
            headers={"User-Agent": "dolymarket-oracle-verifier/1.0"},
        ) as resp:
            if resp.status_code >= 400:
                raise HTTPException(
                    status_code=502,
                    detail=f"Evidence URL returned HTTP {resp.status_code}",
                )
            ctype = (resp.headers.get("content-type") or "text/plain").split(";")[0].strip().lower()
            if ctype and not ctype.startswith(_ALLOWED_CONTENT_PREFIXES):
                raise HTTPException(
                    status_code=422,
                    detail=f"Unsupported evidence Content-Type: {ctype}",
                )
            buf = bytearray()
            async for chunk in resp.aiter_bytes():
                remaining = max_bytes - len(buf)
                if remaining <= 0:
                    break
                buf.extend(chunk[:remaining])
                if len(buf) >= max_bytes:
                    break
            raw_text = bytes(buf).decode("utf-8", errors="replace")
            text = _TAG_RE.sub(" ", raw_text)
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
    resolution_criteria: str | None = None,
    oracle_threshold: float | None = None,
    oracle_comparator: str | None = None,
) -> dict[str, Any]:
    """Verify whether cited evidence supports or contradicts a proposed resolution.

    Enforces Kalshi-style Source Agency domain whitelisting when `resolution_criteria`
    declares allowed sources (`Outcome verified from ...`).
    """
    from app.services.oracle_evidence_s1 import (
        is_allowed_source_url,
        parse_kalshi_rules,
        predict_evidence_s1,
    )

    rules = parse_kalshi_rules(resolution_criteria)
    if source_url:
        _validate_public_http_url(source_url)
        if rules["allowed_domains"] and not is_allowed_source_url(
            source_url, rules["allowed_domains"]
        ):
            raise HTTPException(
                status_code=422,
                detail="source_url domain is not an approved Source Agency for this market",
            )

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

    s1_pred = predict_evidence_s1(
        question,
        proposed_outcome,
        text,
        resolution_criteria=resolution_criteria,
        oracle_threshold=oracle_threshold,
        oracle_comparator=oracle_comparator,
    )
    if s1_pred is not None:
        return s1_pred

    return _local_entailment(question, proposed_outcome, text)


def resolve_expired_no_data(
    resolution_criteria: str | None,
    *,
    has_verified_yes_evidence: bool = False,
) -> dict[str, Any] | None:
    """Kalshi Rule 3: if expired with no Source Agency data, deterministically resolve NO."""
    from app.services.oracle_evidence_s1 import parse_kalshi_rules

    if has_verified_yes_evidence:
        return None
    rules = parse_kalshi_rules(resolution_criteria)
    if not rules["no_data_resolves_no"]:
        return None
    return {
        "outcome": "NO",
        "confidence": 1.0,
        "mode": "kalshi_no_data_default",
    }
