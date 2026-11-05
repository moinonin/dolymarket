"""Passkey (WebAuthn) registration and sign-in ceremonies."""
import pytest
from httpx import AsyncClient

from tests.conftest import auth_headers
from tests.webauthn_helpers import SoftwareAuthenticator

pytestmark = pytest.mark.asyncio

RP_ID = "localhost"
ORIGIN = "http://test"


async def test_passkey_registration_then_login(client: AsyncClient, monkeypatch):
    monkeypatch.setenv("WEBAUTHN_RP_ID", RP_ID)
    monkeypatch.setenv("WEBAUTHN_ORIGIN", ORIGIN)

    headers = await auth_headers(client, "passkey-trader@example.com")
    authenticator = SoftwareAuthenticator(RP_ID, ORIGIN)

    options = await client.post(
        "/api/v1/auth/passkey/register/options", headers=headers
    )
    assert options.status_code == 200, options.text
    body = options.json()
    assert body["rp"]["id"] == RP_ID
    assert body["challenge"]
    assert body["publicKey"]["rp"]["id"] == RP_ID

    credential = authenticator.registration_response(body["challenge"])
    verified = await client.post(
        "/api/v1/auth/passkey/register/verify",
        json={"credential": credential, "label": "Laptop"},
        headers=headers,
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["status"] == "registered"
    assert verified.json()["credential_id"] == credential["id"]

    listing = await client.get("/api/v1/auth/passkey/credentials", headers=headers)
    assert listing.status_code == 200
    passkeys = listing.json()["passkeys"]
    assert len(passkeys) == 1
    assert passkeys[0]["label"] == "Laptop"

    login_options = await client.post("/api/v1/auth/passkey/login/options")
    assert login_options.status_code == 200, login_options.text
    assertion = authenticator.assertion_response(login_options.json()["challenge"])
    login = await client.post(
        "/api/v1/auth/passkey/login/verify", json={"credential": assertion}
    )
    assert login.status_code == 200, login.text
    assert login.json()["access_token"]
    assert login.json()["user"]["email"] == "passkey-trader@example.com"

    # The sign counter must advance with every successful assertion.
    listing = await client.get("/api/v1/auth/passkey/credentials", headers=headers)
    assert listing.json()["passkeys"][0]["sign_count"] >= 1

    # Replaying the same assertion must fail: the challenge was consumed.
    replay = await client.post(
        "/api/v1/auth/passkey/login/verify", json={"credential": assertion}
    )
    assert replay.status_code in (400, 401)


async def test_passkey_login_rejects_tampered_signature(
    client: AsyncClient, monkeypatch
):
    monkeypatch.setenv("WEBAUTHN_RP_ID", RP_ID)
    monkeypatch.setenv("WEBAUTHN_ORIGIN", ORIGIN)

    headers = await auth_headers(client, "passkey-tamper@example.com")
    authenticator = SoftwareAuthenticator(RP_ID, ORIGIN)

    options = await client.post(
        "/api/v1/auth/passkey/register/options", headers=headers
    )
    credential = authenticator.registration_response(options.json()["challenge"])
    verified = await client.post(
        "/api/v1/auth/passkey/register/verify",
        json={"credential": credential},
        headers=headers,
    )
    assert verified.status_code == 200, verified.text

    login_options = await client.post("/api/v1/auth/passkey/login/options")
    assertion = authenticator.tamper_signature(
        authenticator.assertion_response(login_options.json()["challenge"])
    )
    login = await client.post(
        "/api/v1/auth/passkey/login/verify", json={"credential": assertion}
    )
    assert login.status_code == 401, login.text


async def test_passkey_endpoints_require_the_right_principal(client: AsyncClient):
    # Registration options need an authenticated user.
    anonymous = await client.post("/api/v1/auth/passkey/register/options")
    assert anonymous.status_code == 401

    # Login options are public, but an unknown credential cannot sign in.
    headers = await auth_headers(client, "passkey-unknown@example.com")
    login_options = await client.post("/api/v1/auth/passkey/login/options")
    assert login_options.status_code == 200
    unknown = await client.post(
        "/api/v1/auth/passkey/login/verify",
        json={
            "credential": {
                "id": "not-a-real-credential",
                "rawId": "not-a-real-credential",
                "type": "public-key",
                "response": {"clientDataJSON": "e30"},
            }
        },
    )
    assert unknown.status_code == 404

    # Listing passkeys is scoped to the caller.
    listing = await client.get("/api/v1/auth/passkey/credentials", headers=headers)
    assert listing.status_code == 200
    assert listing.json()["passkeys"] == []
