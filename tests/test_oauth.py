"""OAuth 2.0 authorization-code flow for Google / Microsoft / Apple."""
import pytest
from httpx import AsyncClient

from app.core import security
from app.services import oauth as oauth_service

pytestmark = pytest.mark.asyncio


async def test_provider_status_lists_supported_providers(client: AsyncClient):
    res = await client.get("/api/v1/auth/oauth/providers")
    assert res.status_code == 200, res.text
    providers = {p["name"]: p for p in res.json()["providers"]}
    assert set(providers) == {"google", "microsoft", "apple"}
    assert providers["apple"]["label"] == "Apple"
    # Without credentials in the environment the providers report as unset.
    assert providers["google"]["configured"] is False


async def test_oauth_start_requires_provider_configuration(
    client: AsyncClient, monkeypatch
):
    unconfigured = await client.get("/api/v1/auth/oauth/google/start")
    assert unconfigured.status_code == 503

    monkeypatch.setenv("GOOGLE_CLIENT_ID", "google-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "google-client-secret")
    res = await client.get("/api/v1/auth/oauth/google/start")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["configured"] is True
    assert data["auth_url"].startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "client_id=google-client-id" in data["auth_url"]
    assert "code_challenge=" in data["auth_url"]
    assert data["redirect_uri"].endswith("/api/v1/auth/oauth/google/callback")
    assert data["state"]


async def test_oauth_start_rejects_unknown_provider(client: AsyncClient):
    res = await client.get("/api/v1/auth/oauth/myspace/start")
    assert res.status_code == 404


async def test_oauth_callback_creates_account_and_exchange_code(
    client: AsyncClient, monkeypatch
):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "google-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "google-client-secret")

    async def fake_exchange(provider, code, redirect_uri, code_verifier=None):
        return {"access_token": "provider-token", "id_token": "provider-id-token"}

    async def fake_profile(provider, tokens):
        return {
            "subject": "google-subject-1",
            "email": "oauth-trader@example.com",
            "email_verified": True,
            "name": "OAuth Trader",
        }

    monkeypatch.setattr(oauth_service, "exchange_code", fake_exchange)
    monkeypatch.setattr(oauth_service, "fetch_profile", fake_profile)

    state = security.create_signed_state(
        {"provider": "google", "code_verifier": "verifier", "redirect": False}
    )
    callback = await client.get(
        f"/api/v1/auth/oauth/google/callback?code=auth-code&state={state}"
    )
    assert callback.status_code == 200, callback.text
    exchange_code = callback.json()["exchange_code"]
    assert callback.json()["expires_in"] > 0

    token = await client.post(
        "/api/v1/auth/oauth/exchange", json={"code": exchange_code}
    )
    assert token.status_code == 200, token.text
    assert token.json()["access_token"]
    assert token.json()["token_type"] == "bearer"
    assert token.json()["user"]["email"] == "oauth-trader@example.com"

    # The code is single use.
    replay = await client.post(
        "/api/v1/auth/oauth/exchange", json={"code": exchange_code}
    )
    assert replay.status_code == 400

    # The new account owns a collateral account and can use the API.
    balance = await client.get(
        "/api/v1/collateral/balance",
        headers={"Authorization": f"Bearer {token.json()['access_token']}"},
    )
    assert balance.status_code == 200


async def test_oauth_callback_links_existing_email_account(
    client: AsyncClient, monkeypatch
):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "google-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "google-client-secret")

    from tests.conftest import auth_headers

    headers = await auth_headers(client, "linkable@example.com")
    balance = await client.get("/api/v1/collateral/balance", headers=headers)
    assert balance.status_code == 200
    user_id = balance.json()["user_id"]

    async def fake_exchange(provider, code, redirect_uri, code_verifier=None):
        return {"access_token": "provider-token"}

    async def fake_profile(provider, tokens):
        return {
            "subject": "google-subject-2",
            "email": "linkable@example.com",
            "email_verified": True,
            "name": None,
        }

    monkeypatch.setattr(oauth_service, "exchange_code", fake_exchange)
    monkeypatch.setattr(oauth_service, "fetch_profile", fake_profile)

    state = security.create_signed_state(
        {"provider": "google", "code_verifier": "verifier", "redirect": True}
    )
    callback = await client.get(
        f"/api/v1/auth/oauth/google/callback?code=auth-code&state={state}"
    )
    assert callback.status_code == 307, callback.text
    location = callback.headers["location"]
    assert "oauth_code=" in location

    code = location.split("oauth_code=", 1)[1]
    token = await client.post("/api/v1/auth/oauth/exchange", json={"code": code})
    assert token.status_code == 200, token.text
    # Linking reuses the existing account instead of creating a duplicate.
    assert token.json()["user"]["id"] == user_id


async def test_oauth_callback_rejects_bad_state(client: AsyncClient, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "google-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "google-client-secret")

    bad_state = await client.get(
        "/api/v1/auth/oauth/google/callback?code=auth-code&state=tampered"
    )
    assert bad_state.status_code == 400

    mismatched = security.create_signed_state(
        {"provider": "microsoft", "code_verifier": "v", "redirect": False}
    )
    wrong_provider = await client.get(
        f"/api/v1/auth/oauth/google/callback?code=auth-code&state={mismatched}"
    )
    assert wrong_provider.status_code == 400


async def test_oauth_exchange_rejects_unknown_code(client: AsyncClient):
    res = await client.post(
        "/api/v1/auth/oauth/exchange", json={"code": "definitely-not-a-code"}
    )
    assert res.status_code == 400
