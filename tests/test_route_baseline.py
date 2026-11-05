"""Regression baseline: changes to this project are additive, not a rewrite.

``.githeri/baseline.json`` is the pre-change endpoint contract captured by
``githeri baseline``. If any endpoint in it stops resolving, an existing
contract was dropped — the concrete signature of a rewrite replacing working
code. Adding endpoints is expected and does not fail this test; only removals
do.

The comparison uses ``app.openapi()`` rather than decorator source, because the
framework applies ``APIRouter`` prefixes itself. That is the same resolved view
``githeri verify`` audits.
"""
import json
from pathlib import Path

import pytest

BASELINE_PATH = Path(__file__).resolve().parent.parent / ".githeri" / "baseline.json"
METHODS = {"get", "post", "put", "patch", "delete"}


def _resolved_routes(fastapi_app) -> set[tuple[str, str]]:
    return {
        (method.upper(), path)
        for path, operations in fastapi_app.openapi()["paths"].items()
        for method in operations
        if method.lower() in METHODS
    }


def test_baseline_endpoints_still_resolve(app):
    if not BASELINE_PATH.is_file():
        pytest.skip("no route baseline captured")

    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    expected = {(r["method"].upper(), r["path"]) for r in baseline.get("routes", [])}
    missing = sorted(expected - _resolved_routes(app))

    assert not missing, f"Existing endpoints were removed: {missing}"
