"""WebAuthn (passkey) endpoints.

Four ceremonies make up the contract:

* ``POST /api/v1/auth/passkey/register/options`` - creation options for an
  authenticated user who wants to enrol a passkey.
* ``POST /api/v1/auth/passkey/register/verify``   - verify the attestation and
  store the credential (public key + sign counter).
* ``POST /api/v1/auth/passkey/login/options``     - request options for a
  sign-in assertion.
* ``POST /api/v1/auth/passkey/login/verify``      - verify the assertion and
  issue a JWT access token.

Challenges are single-use and stored server-side so a ceremony can never be
replayed, and every assertion must increment the authenticator's sign counter.
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.exceptions import (
    InvalidAuthenticationResponse,
    InvalidRegistrationResponse,
)
from webauthn.helpers.options_to_json_dict import options_to_json_dict
from webauthn.helpers.structs import (
    AttestationConveyancePreference,
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.api.deps import get_current_user
from app.core import security
from app.db.session import get_async_session
from app.models.domain import PasskeyChallenge, PasskeyCredential, User

router = APIRouter(prefix="/api/v1/auth/passkey", tags=["auth"])

CHALLENGE_TTL_SECONDS = 300


class PasskeyVerifyRequest(BaseModel):
    """Accepts the browser credential object or the split credential form."""

    credential: dict | None = None
    credential_id: str | None = None
    response: dict | None = None
    label: str | None = Field(default=None, max_length=120)


def _rp_id() -> str:
    return os.environ.get("WEBAUTHN_RP_ID", "localhost").strip() or "localhost"


def _rp_name() -> str:
    return os.environ.get("WEBAUTHN_RP_NAME", "Dolymarket").strip() or "Dolymarket"


def _origins() -> list[str]:
    raw = os.environ.get("WEBAUTHN_ORIGINS", "").strip()
    if raw:
        origins = [o.strip() for o in raw.split(",") if o.strip()]
        if origins:
            return origins
    default = os.environ.get("WEBAUTHN_ORIGIN", "http://localhost:8000").strip()
    return [default or "http://localhost:8000"]


def _credential_payload(body: PasskeyVerifyRequest) -> dict:
    """Normalise the two accepted request shapes into a WebAuthn credential."""
    if body.credential:
        return body.credential
    if body.credential_id and body.response is not None:
        response = dict(body.response)
        return {
            "id": body.credential_id,
            "rawId": response.get("rawId", body.credential_id),
            "response": response,
            "type": "public-key",
        }
    raise HTTPException(status_code=400, detail="Missing passkey credential payload")


def _client_data(payload: dict) -> dict:
    """Decode ``clientDataJSON`` from a credential payload."""
    response = payload.get("response")
    if not isinstance(response, dict):
        raise HTTPException(status_code=400, detail="Malformed passkey credential")
    client_data = response.get("clientDataJSON")
    if not isinstance(client_data, str):
        raise HTTPException(status_code=400, detail="Missing clientDataJSON")
    try:
        raw = base64url_to_bytes(client_data)
        data = json.loads(raw)
    except Exception as exc:  # malformed client data
        raise HTTPException(status_code=400, detail="Malformed clientDataJSON") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Malformed clientDataJSON")
    return data


async def _store_challenge(
    session: AsyncSession, challenge: bytes, kind: str, user_id: str | None
) -> None:
    session.add(
        PasskeyChallenge(
            user_id=user_id,
            challenge=bytes_to_base64url(challenge),
            kind=kind,
            expires_at=datetime.now(UTC) + timedelta(seconds=CHALLENGE_TTL_SECONDS),
        )
    )
    await session.flush()


async def _take_challenge(
    session: AsyncSession, challenge: bytes, kind: str, user_id: str | None
) -> PasskeyChallenge:
    """Fetch and consume a pending challenge (single use)."""
    try:
        encoded = bytes_to_base64url(challenge)
    except Exception as exc:  # malformed challenge
        raise HTTPException(status_code=400, detail="Malformed passkey challenge") from exc
    row = (
        await session.execute(
            select(PasskeyChallenge).where(PasskeyChallenge.challenge == encoded)
        )
    ).scalar_one_or_none()
    if row is None or row.kind != kind:
        raise HTTPException(status_code=400, detail="Unknown passkey challenge")
    if row.user_id != user_id:
        raise HTTPException(status_code=400, detail="Passkey challenge mismatch")
    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at < datetime.now(UTC):
        raise HTTPException(status_code=400, detail="Passkey challenge expired")
    await session.delete(row)
    await session.flush()
    return row


@router.post("/register/options")
async def passkey_register_options(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Creation options for enrolling a new passkey."""
    existing = (
        await session.execute(
            select(PasskeyCredential).where(PasskeyCredential.user_id == user.id)
        )
    ).scalars().all()
    exclude = []
    for cred in existing:
        transports = []
        for raw in cred.transports or []:
            try:
                transports.append(AuthenticatorTransport(raw))
            except ValueError:
                continue
        exclude.append(
            PublicKeyCredentialDescriptor(
                id=base64url_to_bytes(cred.credential_id),
                transports=transports or None,
            )
        )

    options = generate_registration_options(
        rp_id=_rp_id(),
        rp_name=_rp_name(),
        user_id=user.id.encode("utf-8"),
        user_name=user.email,
        user_display_name=user.email,
        attestation=AttestationConveyancePreference.NONE,
        exclude_credentials=exclude,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.PREFERRED,
        ),
    )
    await _store_challenge(session, options.challenge, "registration", user.id)
    return {
        "publicKey": options_to_json_dict(options),
        "challenge": bytes_to_base64url(options.challenge),
        "rp": {"id": _rp_id(), "name": _rp_name()},
    }


@router.post("/register/verify")
async def passkey_register_verify(
    body: PasskeyVerifyRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Verify an attestation and persist the credential."""
    payload = _credential_payload(body)
    client_data = _client_data(payload)
    challenge_b64 = client_data.get("challenge")
    if not challenge_b64:
        raise HTTPException(status_code=400, detail="Missing passkey challenge")
    issued = await _take_challenge(
        session, base64url_to_bytes(challenge_b64), "registration", user.id
    )

    try:
        verified = verify_registration_response(
            credential=payload,
            expected_challenge=base64url_to_bytes(issued.challenge),
            expected_rp_id=_rp_id(),
            expected_origin=_origins(),
        )
    except (InvalidRegistrationResponse, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid passkey: {exc}") from exc

    transports = None
    raw_transports = (payload.get("response") or {}).get("transports")
    if isinstance(raw_transports, list):
        transports = [str(t) for t in raw_transports]

    credential_id = bytes_to_base64url(verified.credential_id)
    existing = (
        await session.execute(
            select(PasskeyCredential).where(
                PasskeyCredential.credential_id == credential_id
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Passkey already registered")

    session.add(
        PasskeyCredential(
            user_id=user.id,
            credential_id=credential_id,
            public_key=verified.credential_public_key,
            sign_count=verified.sign_count,
            aaguid=verified.aaguid,
            transports=transports,
            backed_up=bool(verified.credential_backed_up),
            device_type=str(getattr(verified.credential_device_type, "value", "")),
            label=body.label,
        )
    )
    await session.flush()
    return {
        "status": "registered",
        "credential_id": credential_id,
        "user": {"id": user.id, "email": user.email},
    }


@router.post("/login/options")
async def passkey_login_options(
    session: AsyncSession = Depends(get_async_session),
):
    """Request options for a passkey sign-in assertion."""
    options = generate_authentication_options(
        rp_id=_rp_id(),
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    await _store_challenge(session, options.challenge, "authentication", None)
    return {
        "publicKey": options_to_json_dict(options),
        "challenge": bytes_to_base64url(options.challenge),
        "rp": {"id": _rp_id(), "name": _rp_name()},
    }


@router.post("/login/verify")
async def passkey_login_verify(
    body: PasskeyVerifyRequest,
    session: AsyncSession = Depends(get_async_session),
):
    """Verify a passkey assertion and issue an access token."""
    payload = _credential_payload(body)
    credential_id = payload.get("id") or body.credential_id
    if not credential_id:
        raise HTTPException(status_code=400, detail="Missing passkey credential id")

    row = (
        await session.execute(
            select(PasskeyCredential).where(
                PasskeyCredential.credential_id == credential_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown passkey")

    client_data = _client_data(payload)
    challenge_b64 = client_data.get("challenge")
    if not challenge_b64:
        raise HTTPException(status_code=400, detail="Missing passkey challenge")
    issued = await _take_challenge(
        session, base64url_to_bytes(challenge_b64), "authentication", None
    )

    try:
        verified = verify_authentication_response(
            credential=payload,
            expected_challenge=base64url_to_bytes(issued.challenge),
            expected_rp_id=_rp_id(),
            expected_origin=_origins(),
            credential_public_key=row.public_key,
            credential_current_sign_count=row.sign_count,
        )
    except (InvalidAuthenticationResponse, ValueError) as exc:
        raise HTTPException(status_code=401, detail=f"Invalid passkey: {exc}") from exc

    row.sign_count = max(row.sign_count, verified.new_sign_count)
    row.last_used_at = datetime.now(UTC)
    user = (
        await session.execute(select(User).where(User.id == row.user_id))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="Passkey has no account")
    await session.flush()

    token = security.create_access_token(user.id, user.email)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "created_at": str(user.created_at),
        },
    }


@router.get("/credentials")
async def list_passkeys(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """List the passkeys registered by the authenticated user."""
    rows = (
        await session.execute(
            select(PasskeyCredential).where(PasskeyCredential.user_id == user.id)
        )
    ).scalars().all()
    return {
        "passkeys": [
            {
                "credential_id": r.credential_id,
                "label": r.label,
                "aaguid": r.aaguid,
                "device_type": r.device_type,
                "backed_up": r.backed_up,
                "sign_count": r.sign_count,
                "created_at": str(r.created_at),
                "last_used_at": str(r.last_used_at) if r.last_used_at else None,
            }
            for r in rows
        ]
    }


@router.delete("/credentials/{credential_id}")
async def delete_passkey(
    credential_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Revoke one of the authenticated user's passkeys."""
    row = (
        await session.execute(
            select(PasskeyCredential).where(
                PasskeyCredential.credential_id == credential_id,
                PasskeyCredential.user_id == user.id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Passkey not found")
    await session.delete(row)
    await session.flush()
    return {"status": "deleted", "credential_id": credential_id}
