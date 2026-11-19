#!/usr/bin/env python3
"""DexBuilder Readiness Handoff Verifier.

Runs all checks that work today (offline tests, HMAC signing, public REST feed,
signed credential probe) and, with `--live`, verifies post-permission endpoints
(`event_contracts` broker reads + WebSocket handshake).

Usage:
    python scripts/verify_dexbuilder_readiness.py          # pre-permission checks (safe now)
    python scripts/verify_dexbuilder_readiness.py --live   # full post-permission checks
"""
from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def _print_result(name: str, ok: bool, detail: str, *, advisory: bool = False) -> bool:
    tag = "PASS" if ok else ("WARN" if advisory else "FAIL")
    print(f"[{tag}] {name}: {detail}")
    return ok or advisory


def check_env_and_signing() -> bool:
    """Verify DexBuilder settings and deterministic HMAC-SHA512 signing."""
    from app.services.dexbuilder import (
        DexBuilderClient,
        canonical_signature_message,
        get_config,
        sign_payload,
    )

    cfg = get_config()
    client = DexBuilderClient()
    configured = client.enabled
    force_dry = os.getenv("DEXBUILDER_FORCE_DRY_RUN", "").lower() in {"1", "true", "yes"}

    ok_cfg = _print_result(
        "Config",
        configured,
        f"enabled={configured}, base={cfg.DEXBUILDER_API_BASE}, dry_run_override={force_dry}",
    )

    msg = canonical_signature_message("GET", "/api/v4/dexbuilder/assets", "limit=10", "", "1700000000")
    sig = sign_payload("test-secret", msg)
    ok_sig = _print_result(
        "HMAC-SHA512 Signing",
        len(sig) == 128 and msg.count("\n") == 4,
        f"digest_len={len(sig)}",
    )
    return ok_cfg and ok_sig


def run_offline_pytest() -> bool:
    """Run local DexBuilder auth, parity, and stream test suites."""
    test_files = [
        "tests/test_dexbuilder_auth.py",
        "tests/test_dexbuilder_parity.py",
        "tests/test_dexbuilder_stream.py",
    ]
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *test_files],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    summary_line = (proc.stdout.strip().splitlines() or ["no output"])[-1]
    return _print_result("Offline DexBuilder Tests", proc.returncode == 0, summary_line)


async def check_public_rest() -> bool:
    """Probe public DexBuilder prediction endpoints (no permission required)."""
    from app.services.dexbuilder import DexBuilderClient

    client = DexBuilderClient()
    all_ok = True
    try:
        t = await client.get_time()
        all_ok &= _print_result("Public Time", bool(t), f"keys={list(t.keys()) if isinstance(t, dict) else type(t).__name__}")
    except Exception as exc:
        all_ok &= _print_result("Public Time", False, repr(exc))

    try:
        events = await client.get_events(limit=3)
        count = len(events.get("items", events)) if isinstance(events, dict) else len(events)
        all_ok &= _print_result("Public Events", count >= 0, f"returned={count} items")
    except Exception as exc:
        all_ok &= _print_result("Public Events", False, repr(exc))

    try:
        markets = await client.get_markets(status="active", limit=3)
        count = len(markets.get("items", markets)) if isinstance(markets, dict) else len(markets)
        all_ok &= _print_result("Public Markets", count >= 0, f"returned={count} items")
    except Exception as exc:
        all_ok &= _print_result("Public Markets", False, repr(exc))

    return all_ok


async def check_signed_credentials(*, live_mode: bool) -> bool:
    """Probe signed credential diagnostic (`check_credentials`)."""
    from app.services.dexbuilder import DexBuilderAuthError, DexBuilderClient

    client = DexBuilderClient()
    try:
        res = await client.check_credentials()
        return _print_result("Signed Auth Probe", True, f"ok={res}")
    except DexBuilderAuthError as exc:
        return _print_result(
            "Signed Auth Probe",
            False,
            f"{exc.label} (HTTP {exc.status_code})",
            advisory=not live_mode,
        )
    except Exception as exc:
        return _print_result("Signed Auth Probe", False, repr(exc), advisory=not live_mode)


async def check_post_permission_surfaces() -> bool:
    """Verify broker & WebSocket surfaces expected after `event_contracts` activation."""
    import httpx
    from app.services.dexbuilder import DEFAULT_WS, DexBuilderClient

    client = DexBuilderClient()
    all_ok = True

    for label, coro in [
        ("Broker Platform Assets", client.get_platform_assets()),
        ("Broker Account Book", client.get_account_book()),
    ]:
        try:
            data = await coro
            all_ok &= _print_result(label, data is not None, "HTTP 200")
        except Exception as exc:
            all_ok &= _print_result(label, False, repr(exc))

    ws_http = DEFAULT_WS.replace("wss://", "https://").replace("ws://", "http://")
    try:
        async with httpx.AsyncClient(timeout=5.0) as http:
            resp = await http.get(ws_http)
            ok_ws = resp.status_code in (101, 400, 426)
            all_ok &= _print_result("Broker WS Endpoint", ok_ws, f"HTTP {resp.status_code}")
    except Exception as exc:
        all_ok &= _print_result("Broker WS Endpoint", False, repr(exc))

    return all_ok


async def async_main(live_mode: bool) -> int:
    print(f"=== DexBuilder Readiness Handoff ({'LIVE' if live_mode else 'PRE-PERMISSION'}) ===")
    ok = True
    ok &= check_env_and_signing()
    ok &= run_offline_pytest()
    ok &= await check_public_rest()
    ok &= await check_signed_credentials(live_mode=live_mode)
    if live_mode:
        ok &= await check_post_permission_surfaces()
    print("=== Result:", "READY ===" if ok else "BLOCKED (see FAIL lines) ===")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify DexBuilder readiness.")
    parser.add_argument("--live", action="store_true", help="Fail on upstream permission/WS blockers.")
    args = parser.parse_args()
    return asyncio.run(async_main(args.live))


if __name__ == "__main__":
    raise SystemExit(main())
