"""Minimal software authenticator used to exercise the WebAuthn ceremonies.

The browser APIs (``navigator.credentials.create`` / ``.get``) are not
available in the test environment, so this helper produces byte-exact
responses for an ES256 (P-256) authenticator:

* ``none`` format attestation for the registration ceremony
* an ECDSA-SHA256 assertion for the authentication ceremony

It lets the backend verification path (challenge matching, RP ID hash, origin
check, signature verification and sign-counter tracking) run end to end.
"""
from __future__ import annotations

import base64
import hashlib
import json

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import (
    decode_dss_signature,
    encode_dss_signature,
)

FLAG_UP = 0x01
FLAG_UV = 0x04
FLAG_AT = 0x40


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def unb64url(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


class SoftwareAuthenticator:
    """A P-256 authenticator with a stable credential id and key pair."""

    def __init__(self, rp_id: str, origin: str, credential_id: bytes | None = None):
        self.rp_id = rp_id
        self.origin = origin
        self.credential_id = credential_id or hashlib.sha256(
            f"{rp_id}:{origin}:credential".encode()
        ).digest()[:16]
        self.private_key = ec.generate_private_key(ec.SECP256R1())
        self.sign_count = 0

    # ------------------------------------------------------------------ keys
    def _public_numbers(self):
        numbers = self.private_key.public_key().public_numbers()
        x = numbers.x.to_bytes(32, "big")
        y = numbers.y.to_bytes(32, "big")
        return x, y

    def _cose_key(self) -> bytes:
        x, y = self._public_numbers()
        return cbor2.dumps(
            {
                1: 2,  # kty: EC2
                3: -7,  # alg: ES256
                -1: 1,  # crv: P-256
                -2: x,
                -3: y,
            }
        )

    # ------------------------------------------------------------ ceremonies
    def _client_data(self, ceremony: str, challenge: str) -> bytes:
        return json.dumps(
            {
                "type": ceremony,
                "challenge": challenge,
                "origin": self.origin,
                "crossOrigin": False,
            },
            separators=(",", ":"),
        ).encode()

    def _authenticator_data(self, flags: int, attested: bool) -> bytes:
        data = hashlib.sha256(self.rp_id.encode()).digest()
        data += bytes([flags])
        data += self.sign_count.to_bytes(4, "big")
        if attested:
            data += b"\x00" * 16  # zero AAGUID
            data += len(self.credential_id).to_bytes(2, "big")
            data += self.credential_id
            data += self._cose_key()
        return data

    def registration_response(self, challenge: str) -> dict:
        """Build a ``webauthn.create`` response for the given challenge."""
        client_data = self._client_data("webauthn.create", challenge)
        auth_data = self._authenticator_data(FLAG_UP | FLAG_AT, attested=True)
        attestation = cbor2.dumps(
            {"fmt": "none", "attStmt": {}, "authData": auth_data}
        )
        return {
            "id": b64url(self.credential_id),
            "rawId": b64url(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": b64url(client_data),
                "attestationObject": b64url(attestation),
                "transports": ["internal", "hybrid"],
            },
        }

    def assertion_response(self, challenge: str, sign_count: int | None = None) -> dict:
        """Build a ``webauthn.get`` response for the given challenge."""
        if sign_count is not None:
            self.sign_count = sign_count
        else:
            self.sign_count += 1
        client_data = self._client_data("webauthn.get", challenge)
        auth_data = self._authenticator_data(FLAG_UP | FLAG_UV, attested=False)
        signature = self.private_key.sign(
            auth_data + hashlib.sha256(client_data).digest(),
            ec.ECDSA(hashes.SHA256()),
        )
        return {
            "id": b64url(self.credential_id),
            "rawId": b64url(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": b64url(client_data),
                "authenticatorData": b64url(auth_data),
                "signature": b64url(signature),
                "userHandle": None,
            },
        }

    def tamper_signature(self, response: dict) -> dict:
        """Flip a byte in the signature so verification must fail."""
        raw = bytearray(unb64url(response["response"]["signature"]))
        raw[-1] ^= 0xFF
        response["response"]["signature"] = b64url(bytes(raw))
        return response


def der_to_raw(signature: bytes) -> tuple[int, int]:
    r, s = decode_dss_signature(signature)
    return r, s


def raw_to_der(r: int, s: int) -> bytes:
    return encode_dss_signature(r, s)
