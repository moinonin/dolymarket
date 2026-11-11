"""AGX REST surface: route resolution, authorization, validation, serialization."""
import pytest
from httpx import AsyncClient

from tests.conftest import auth_headers, make_admin

pytestmark = pytest.mark.asyncio


AGX_ROUTES = {
    "/api/v1/agx/stake": {"post"},
    "/api/v1/agx/unstake": {"post"},
    "/api/v1/agx/withdraw": {"post"},
    "/api/v1/agx/balance": {"get"},
    "/api/v1/agx/stakes": {"get"},
    "/api/v1/agx/claim-rewards": {"post"},
    "/api/v1/agx/rewards/history": {"get"},
    "/api/v1/agx/tiers": {"get"},
    "/api/v1/agx/dispute-stake": {"post"},
    "/api/v1/agx/dispute-stakes": {"get"},
    "/api/v1/agx/sync-balance": {"post"},
    "/api/v1/agx/stats": {"get"},
    "/api/v1/agx/epochs/distribute": {"post"},
    "/api/v1/agx/epochs": {"get"},
}

AUTHENTICATED_CALLS = [
    ("get", "/api/v1/agx/balance", None),
    ("get", "/api/v1/agx/stakes", None),
    ("post", "/api/v1/agx/claim-rewards", None),
    ("get", "/api/v1/agx/rewards/history", None),
    ("post", "/api/v1/agx/stake", {"amount": "100"}),
    ("post", "/api/v1/agx/unstake", {"stake_id": "unknown"}),
    ("post", "/api/v1/agx/withdraw", {"cooldown_id": "unknown"}),
    ("post", "/api/v1/agx/dispute-stake", {"market_id": "unknown"}),
    ("get", "/api/v1/agx/dispute-stakes", None),
    ("post", "/api/v1/agx/sync-balance", {"verified_balance": "1"}),
    ("post", "/api/v1/agx/epochs/distribute", {"total_fees_collected": "1"}),
]


async def test_every_contracted_route_is_registered(app):
    paths = app.openapi()["paths"]
    for path, methods in AGX_ROUTES.items():
        assert path in paths, f"missing AGX path {path}"
        assert methods.issubset(set(paths[path])), (
            f"{path} exposes {sorted(paths[path])}, expected {sorted(methods)}"
        )
    assert len(paths) >= len(AGX_ROUTES)


async def test_authenticated_routes_reject_anonymous(client: AsyncClient):
    for method, path, body in AUTHENTICATED_CALLS:
        kwargs = {"json": body} if body is not None else {}
        resp = await getattr(client, method)(path, **kwargs)
        assert resp.status_code == 401, f"{method.upper()} {path} -> {resp.status_code}"


async def test_admin_only_routes_reject_regular_users(client: AsyncClient):
    headers = await auth_headers(client, "api-regular@example.com")

    sync = await client.post(
        "/api/v1/agx/sync-balance",
        json={"verified_balance": "1000"},
        headers=headers,
    )
    assert sync.status_code == 403
    assert sync.json()["detail"] == "AGX_FORBIDDEN"

    distribute = await client.post(
        "/api/v1/agx/epochs/distribute",
        json={"total_fees_collected": "10"},
        headers=headers,
    )
    assert distribute.status_code == 403
    assert distribute.json()["detail"] == "AGX_FORBIDDEN"

    balance = (await client.get("/api/v1/agx/balance", headers=headers)).json()
    assert balance["balance"] == "0.000000000000000000"


async def test_sync_balance_is_admin_only_and_idempotent(client: AsyncClient):
    email = "api-sync@example.com"
    headers = await auth_headers(client, email)
    await make_admin(email)

    first = await client.post(
        "/api/v1/agx/sync-balance",
        json={"verified_balance": "250.5"},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    assert first.json()["credited"] == "250.500000000000000000"

    again = await client.post(
        "/api/v1/agx/sync-balance",
        json={"verified_balance": "250.5"},
        headers=headers,
    )
    assert again.status_code == 200
    assert again.json()["credited"] == "0.000000000000000000"
    assert again.json()["balance"]["balance"] == "250.500000000000000000"

    # A lower attestation never debits the off-chain ledger.
    lower = await client.post(
        "/api/v1/agx/sync-balance",
        json={"verified_balance": "100"},
        headers=headers,
    )
    assert lower.status_code == 200
    assert lower.json()["credited"] == "0.000000000000000000"
    assert lower.json()["balance"]["balance"] == "250.500000000000000000"

    negative = await client.post(
        "/api/v1/agx/sync-balance",
        json={"verified_balance": "-1"},
        headers=headers,
    )
    assert negative.status_code == 422
    assert negative.json()["detail"] == "AGX_INVALID_AMOUNT"


async def test_amount_boundary_rejects_non_string_and_garbage(client: AsyncClient):
    email = "api-amounts@example.com"
    headers = await auth_headers(client, email)
    await make_admin(email)

    for payload in ({"amount": 100}, {"amount": 100.0}, {"amount": None}):
        resp = await client.post(
            "/api/v1/agx/stake", json=payload, headers=headers
        )
        assert resp.status_code == 422, resp.text

    for raw in ("not-a-number", "", "NaN", "Infinity", "1,5"):
        garbage = await client.post(
            "/api/v1/agx/stake", json={"amount": raw}, headers=headers
        )
        assert garbage.status_code == 422, f"{raw!r} -> {garbage.status_code}"
        assert garbage.json()["detail"] == "AGX_INVALID_AMOUNT"

    await client.post(
        "/api/v1/agx/sync-balance",
        json={"verified_balance": "1000"},
        headers=headers,
    )
    dispute = await client.post(
        "/api/v1/agx/dispute-stake",
        json={"market_id": "unknown", "amount": 1.5},
        headers=headers,
    )
    assert dispute.status_code == 422


async def test_unknown_identifiers_return_contracted_404(client: AsyncClient):
    email = "api-unknowns@example.com"
    headers = await auth_headers(client, email)
    await make_admin(email)
    await client.post(
        "/api/v1/agx/sync-balance",
        json={"verified_balance": "1000"},
        headers=headers,
    )

    missing_stake = await client.post(
        "/api/v1/agx/unstake",
        json={"stake_id": "00000000-0000-0000-0000-000000000000"},
        headers=headers,
    )
    assert missing_stake.status_code == 404
    assert missing_stake.json()["detail"] == "AGX_STAKE_NOT_FOUND"

    missing_cooldown = await client.post(
        "/api/v1/agx/withdraw",
        json={"cooldown_id": "00000000-0000-0000-0000-000000000000"},
        headers=headers,
    )
    assert missing_cooldown.status_code == 404
    assert missing_cooldown.json()["detail"] == "AGX_COOLDOWN_NOT_FOUND"

    missing_market = await client.post(
        "/api/v1/agx/dispute-stake",
        json={"market_id": "00000000-0000-0000-0000-000000000000"},
        headers=headers,
    )
    assert missing_market.status_code == 404
    assert missing_market.json()["detail"] == "AGX_MARKET_NOT_FOUND"

    missing_epoch = await client.post(
        "/api/v1/agx/epochs/distribute",
        json={"epoch_number": 999},
        headers=headers,
    )
    assert missing_epoch.status_code == 404
    assert missing_epoch.json()["detail"] == "AGX_EPOCH_NOT_FOUND"


async def test_public_tiers_expose_the_contracted_ladder(client: AsyncClient):
    resp = await client.get("/api/v1/agx/tiers")
    assert resp.status_code == 200
    body = resp.json()

    assert [
        (row["tier"], row["min_staked"], row["discount_rate"])
        for row in body["tiers"]
    ] == [
        ("0", "0.000000000000000000", "0.000000000000000000"),
        ("1", "100.000000000000000000", "0.050000000000000000"),
        ("2", "1000.000000000000000000", "0.100000000000000000"),
        ("3", "5000.000000000000000000", "0.150000000000000000"),
    ]
    assert body["total_staked"] == "0.000000000000000000"
    assert body["staker_count"] == 0


async def test_public_stats_and_epoch_listing(client: AsyncClient):
    stats = await client.get("/api/v1/agx/stats")
    assert stats.status_code == 200
    body = stats.json()
    assert body["token_symbol"] == "AGX"
    assert body["token_decimals"] == 18
    assert isinstance(body["chain_id"], int)
    assert body["treasury_address"].startswith("0x")
    for key in (
        "total_staked",
        "total_spendable",
        "total_gating_locked",
        "total_dispute_locked",
        "distributed_staker_pool",
    ):
        assert body[key] == "0.000000000000000000"

    epochs = await client.get("/api/v1/agx/epochs")
    assert epochs.status_code == 200
    assert epochs.json() == {"epochs": []}

    assert (await client.get("/api/v1/agx/epochs?limit=0")).status_code == 422
    assert (await client.get("/api/v1/agx/epochs?limit=201")).status_code == 422


async def test_new_user_balance_is_zero_and_all_amounts_are_strings(
    client: AsyncClient,
):
    headers = await auth_headers(client, "api-fresh@example.com")

    balance = await client.get("/api/v1/agx/balance", headers=headers)
    assert balance.status_code == 200
    body = balance.json()
    for key in (
        "balance",
        "staked_balance",
        "locked_gating_balance",
        "locked_dispute_balance",
        "pending_rewards",
        "discount_rate",
    ):
        assert body[key] == "0.000000000000000000", key
        assert isinstance(body[key], str)
    assert body["tier"] == "0"
    assert body["tier_name"] == "None"

    stakes = await client.get("/api/v1/agx/stakes", headers=headers)
    assert stakes.status_code == 200
    assert stakes.json() == {"stakes": [], "cooldowns": []}

    claim = await client.post("/api/v1/agx/claim-rewards", headers=headers)
    assert claim.status_code == 200
    assert claim.json()["claimed"] == "0.000000000000000000"

    history = await client.get("/api/v1/agx/rewards/history", headers=headers)
    assert history.status_code == 200
    assert history.json() == {"rewards": [], "total": "0.000000000000000000"}
