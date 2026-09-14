"""Google Identity: verify ID tokens with zero new dependencies.

Uses Google's public JWKS via urllib from the standard library — no
``google-auth`` package needed. Tokens are verified for signature (RS256,
kid-matched), issuer, audience (client ID), and expiry.

Configuration (optional):
    MEDFLOW_GOOGLE_CLIENT_ID   in the environment enables Google sign-in
"""

from __future__ import annotations

import base64
import json
import urllib.request
from pathlib import Path

GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")


class GoogleAuthError(Exception):
    """Raised for malformed, forged, or misaudience Google tokens."""


def _b64url_decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def _fetch_jwks(cache_path: Path | None = None) -> dict:
    """Fetch Google's key set, cached on disk for a day."""
    if cache_path is not None and cache_path.exists():
        import time
        if time.time() - cache_path.stat().st_mtime < 86_400:
            try:
                return json.loads(cache_path.read_text())
            except (ValueError, OSError):
                pass
    with urllib.request.urlopen(GOOGLE_JWKS_URL, timeout=10) as response:
        keys = json.loads(response.read().decode())
    if cache_path is not None:
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(keys))
        except OSError:
            pass
    return keys


def _verify_rs256(signing_input: bytes, signature: bytes, jwk: dict) -> bool:
    """RS256 via pure-Python RSA (no cryptography package required)."""
    import hashlib

    n = int.from_bytes(_b64url_decode(jwk["n"]), "big")
    e = int.from_bytes(_b64url_decode(jwk["e"]), "big")
    decoded = pow(int.from_bytes(signature, "big"), e, n)
    # left-pad to full key size: the EM's leading 0x00 vanishes in the int
    digest = decoded.to_bytes(len(signature), "big")
    # EMSA-PKCS1-v1_5 encoding of the SHA-256 digest:
    # 0x00 0x01 PS 0x00 DigestInfo(19) Digest(32), with 2+pad+1+51 = k
    sha256_info = bytes.fromhex("3031300d060960864801650304020105000420")
    pad_len = len(signature) - len(sha256_info) - 35
    expected = b"\x00\x01" + b"\xff" * pad_len + b"\x00" + sha256_info
    expected += hashlib.sha256(signing_input).digest()
    return expected == digest


def verify_google_token(token: str, client_id: str,
                        jwks_cache: Path | None = None) -> dict:
    """Verify signature and claims; return the public profile claims."""
    try:
        header_b64, payload_b64, sig_b64 = token.split(".")
        header = json.loads(_b64url_decode(header_b64))
        payload = json.loads(_b64url_decode(payload_b64))
        signature = _b64url_decode(sig_b64)
    except (ValueError, KeyError) as exc:
        raise GoogleAuthError("Malformed Google token.") from exc

    if header.get("alg") != "RS256":
        raise GoogleAuthError("Unsupported token algorithm.")
    if payload.get("aud") != client_id:
        raise GoogleAuthError("Token was issued to a different application.")
    if payload.get("iss") not in GOOGLE_ISSUERS:
        raise GoogleAuthError("Token issuer is not Google.")
    import time
    if int(payload.get("exp", 0)) < time.time():
        raise GoogleAuthError("Google token has expired.")
    if not payload.get("email_verified"):
        raise GoogleAuthError("Google account email is not verified.")

    keys = _fetch_jwks(jwks_cache)
    key = next((k for k in keys.get("keys", []) if k.get("kid") == header.get("kid")),
               None)
    if key is None:
        raise GoogleAuthError("Unknown signing key.")

    if not _verify_rs256(f"{header_b64}.{payload_b64}".encode(), signature, key):
        raise GoogleAuthError("Signature verification failed.")

    return {
        "sub": payload["sub"],
        "email": payload["email"],
        "name": payload.get("name") or "",
        "picture": payload.get("picture") or "",
    }
