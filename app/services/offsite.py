"""Off-site encrypted cloud backups — the clinic's own storage, zero trust.

The database is a local file; an off-site copy protects it from fire, theft,
disk failure, or losing the whole building. MedFlow uploads **your backup
file** to storage **you own** — any S3-compatible bucket (AWS S3, Backblaze
B2, Cloudflare R2, MinIO…) or any WebDAV share — after encrypting it with a
passphrase only your facility knows. The provider stores an unreadable blob;
patient data is protected end to end, and restore works with nothing but this
code and the passphrase.

Implemented with the standard library only: AWS Signature V4 via hmac/hashlib,
HTTP via urllib. No SDKs, no accounts with MedFlow, nothing to trust but your
own bucket and your own secret.
"""

from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import hmac
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from app.runtime_config import CloudBackupConfig
from app.utils.logging_utils import get_logger

log = get_logger("services.offsite")

# ---------------------------------------------------------------- crypto ----
# AES-256-GCM via the stdlib's hazmat layer. cryptography is already a
# transitive dependency of passlib's argon2 backend, so this adds no new
# package for clinics that install requirements.txt; if it is missing the
# error is explicit and early.


class OffsiteError(Exception):
    """Raised when an off-site operation cannot complete."""


def _aesgcm(key: bytes):
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise OffsiteError(
            "The 'cryptography' package is required for encrypted cloud "
            "backups. Install it with: pip install cryptography") from exc
    return AESGCM(key)


def derive_key(passphrase: str, salt: bytes, iterations: int = 200_000) -> bytes:
    """Turn the facility's passphrase into a 256-bit key (PBKDF2-HMAC-SHA256)."""
    return hashlib.pbkdf2_hmac(
        "sha256", passphrase.encode("utf-8"), salt, iterations)


def encrypt_file(path: Path, passphrase: str) -> tuple[Path, dict]:
    """Encrypt a file into a self-describing blob beside it. Returns (path, header).

    Layout: MAGIC | json-header-len(4) | json-header | ciphertext+tag
    Header carries the salt, iteration count, and nonce — everything needed
    to decrypt with just the passphrase.
    """
    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = derive_key(passphrase, salt)
    plaintext = Path(path).read_bytes()
    ciphertext = _aesgcm(key).encrypt(nonce, plaintext, None)
    header = {
        "v": 1,
        "alg": "AES-256-GCM",
        "kdf": "PBKDF2-HMAC-SHA256",
        "iterations": 200_000,
        "salt": base64.b64encode(salt).decode(),
        "nonce": base64.b64encode(nonce).decode(),
        "original_name": Path(path).name,
        "original_size": len(plaintext),
        "sha256": hashlib.sha256(plaintext).hexdigest(),
    }
    header_bytes = json.dumps(header).encode()
    blob = (b"MFENCBK1" + len(header_bytes).to_bytes(4, "big")
            + header_bytes + ciphertext)
    out = Path(path).with_suffix(path.suffix + ".mfenc")
    out.write_bytes(blob)
    return out, header


def decrypt_file(blob_path: Path, passphrase: str, dest: Path) -> dict:
    """Decrypt an .mfenc blob back into the original database file."""
    blob = Path(blob_path).read_bytes()
    if blob[:8] != b"MFENCBK1":
        raise OffsiteError("That file is not a MedFlow encrypted backup.")
    hlen = int.from_bytes(blob[8:12], "big")
    header = json.loads(blob[12:12 + hlen])
    ciphertext = blob[12 + hlen:]
    key = derive_key(passphrase, base64.b64decode(header["salt"]),
                     header.get("iterations", 200_000))
    try:
        plaintext = _aesgcm(key).decrypt(
            base64.b64decode(header["nonce"]), ciphertext, None)
    except Exception as exc:
        raise OffsiteError(
            "Wrong passphrase, or the file is corrupted.") from exc
    dest.write_bytes(plaintext)
    return header


# ------------------------------------------------------------------- s3 -----

def _sign_s3(cfg: CloudBackupConfig, method: str, key: str, payload: bytes,
             now: _dt.datetime, access: str, secret: str,
             query: str = "") -> dict:
    """AWS Signature V4 headers for a single PUT/GET/DELETE on one object."""
    region = cfg.region or "us-east-1"
    service = "s3"
    host = _s3_host(cfg)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    datestamp = now.strftime("%Y%m%d")
    payload_hash = hashlib.sha256(payload).hexdigest()
    canonical_uri = f"/{cfg.bucket}/{key}"
    canonical_headers = (f"host:{host}\nx-amz-content-sha256:{payload_hash}\n"
                         f"x-amz-date:{amz_date}\n")
    signed_headers = "host;x-amz-content-sha256;x-amz-date"
    canonical_request = "\n".join([
        method, canonical_uri, query, canonical_headers, signed_headers,
        payload_hash])
    scope = f"{datestamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256", amz_date, scope,
        hashlib.sha256(canonical_request.encode()).hexdigest()])
    def _h(key_b: bytes, msg: str) -> bytes:
        return hmac.new(key_b, msg.encode(), hashlib.sha256).digest()
    signing = _h(_h(_h(_h(f"AWS4{secret}".encode(), datestamp),
                       region), service), "aws4_request")
    signature = hmac.new(signing, string_to_sign.encode(),
                         hashlib.sha256).hexdigest()
    return {
        "Authorization": (
            f"AWS4-HMAC-SHA256 Credential={access}/{scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"),
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amz_date,
    }


def _s3_host(cfg: CloudBackupConfig) -> str:
    endpoint = (cfg.endpoint or "").strip()
    if not endpoint:
        raise OffsiteError("No S3 endpoint configured.")
    return endpoint.removeprefix("https://").removeprefix("http://").rstrip("/")


def _s3_request(cfg: CloudBackupConfig, method: str, key: str,
                payload: bytes = b"", access: str = "", secret: str = "",
                timeout: int = 60, query: str = "") -> bytes:
    now = _dt.datetime.now(_dt.timezone.utc)
    scheme = "http" if (cfg.endpoint or "").startswith("http://") else "https"
    host = _s3_host(cfg)
    url = f"{scheme}://{host}/{cfg.bucket}/{key}"
    if query:
        url = f"{url}?{query}"
    headers = _sign_s3(cfg, method, key, payload, now, access, secret,
                       query=query)
    req = urllib.request.Request(url, data=payload if method == "PUT" else None,
                                 headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        raise OffsiteError(
            f"{cfg.provider.title()} returned {exc.code} for {key}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise OffsiteError(f"Could not reach {cfg.provider}: {exc}") from exc


# --------------------------------------------------------------- webdav -----

def _webdav_request(cfg: CloudBackupConfig, method: str, key: str,
                    payload: bytes = b"", user: str = "", password: str = "",
                    timeout: int = 60) -> bytes:
    base = (cfg.endpoint or "").rstrip("/")
    if not base:
        raise OffsiteError("No WebDAV URL configured.")
    folder = (cfg.bucket or "medflow").strip("/")
    url = f"{base}/{folder}/{key}"
    req = urllib.request.Request(url, data=payload if method == "PUT" else None,
                                 method=method)
    import base64 as _b64
    token = _b64.b64encode(f"{user}:{password}".encode()).decode()
    req.add_header("Authorization", f"Basic {token}")
    if method == "PUT":
        req.add_header("Content-Type", "application/octet-stream")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as exc:
        raise OffsiteError(
            f"WebDAV returned {exc.code} for {key}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise OffsiteError(f"Could not reach the WebDAV share: {exc}") from exc


# -------------------------------------------------------------- service -----

class OffsiteBackupService:
    """Upload, list, download, and restore encrypted off-site backups."""

    def __init__(self, cfg: CloudBackupConfig, keys: dict | None = None):
        self.cfg = cfg
        self._keys = keys or {}

    # -- credentials ------------------------------------------------------

    @property
    def credentials(self) -> tuple[str, str]:
        provider = self.cfg.provider
        if provider == "s3":
            return (self._keys.get("access_key_id", ""),
                    self._keys.get("secret_access_key", ""))
        if provider == "webdav":
            return (self._keys.get("username", ""),
                    self._keys.get("password", ""))
        return ("", "")

    def configured(self) -> bool:
        """Ready to upload: provider chosen, endpoint/bucket set, keys present."""
        c = self.cfg
        if not c.enabled or c.provider == "none":
            return False
        user, secret = self.credentials
        if c.provider == "s3":
            return bool(c.endpoint and c.bucket and user and secret)
        if c.provider == "webdav":
            return bool(c.endpoint and user and secret)
        return False

    def _object_key(self, name: str) -> str:
        prefix = (self.cfg.prefix or "").strip("/")
        return f"{prefix}/{name}" if prefix else name

    # -- operations -------------------------------------------------------

    def upload(self, path: Path, passphrase: str) -> dict:
        """Encrypt a backup file and push it off-site. Returns a summary."""
        if not self.configured():
            raise OffsiteError(
                "Cloud backup is not fully configured yet (provider, "
                "endpoint, and access keys are all needed).")
        blob, header = encrypt_file(path, passphrase)
        key = self._object_key(blob.name)
        user, secret = self.credentials
        if self.cfg.provider == "s3":
            _s3_request(self.cfg, "PUT", key, blob.read_bytes(), user, secret)
        else:
            _webdav_request(self.cfg, "PUT", key, blob.read_bytes(), user, secret)
        return {"uploaded": blob.name, "key": key,
                "bytes": blob.stat().st_size, "sha256": header["sha256"]}

    def list_remote(self) -> list[str]:
        """Best-effort listing of stored backup keys."""
        user, secret = self.credentials
        if self.cfg.provider == "s3":
            import re as _re
            prefix = (self.cfg.prefix or "").strip("/")
            query = "list-type=2" + (f"&prefix={prefix}/" if prefix else "")
            body = _s3_request(self.cfg, "GET", "", b"", user, secret,
                               query=query)
            names = _re.findall(rb"<Key>([^<]+)</Key>", body)
            return [n.decode() for n in names]
        # WebDAV PROPFIND — depth 1 XML listing
        base = (self.cfg.endpoint or "").rstrip("/")
        folder = (self.cfg.bucket or "medflow").strip("/")
        url = f"{base}/{folder}/"
        req = urllib.request.Request(url, method="PROPFIND")
        token = base64.b64encode(f"{user}:{secret}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
        req.add_header("Depth", "1")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = resp.read()
        except urllib.error.HTTPError as exc:
            raise OffsiteError(f"WebDAV returned {exc.code} while listing") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise OffsiteError(f"Could not reach the WebDAV share: {exc}") from exc
        import re as _re
        return [h.decode() for h in _re.findall(rb"<d:href>([^<]+)</d:href>", body)]

    def download(self, key: str, dest: Path) -> Path:
        user, secret = self.credentials
        if self.cfg.provider == "s3":
            data = _s3_request(self.cfg, "GET", key, b"", user, secret)
        else:
            name = key.rsplit("/", 1)[-1]
            data = _webdav_request(self.cfg, "GET", name, b"", user, secret)
        dest.write_bytes(data)
        return dest

    def prune_remote(self, keep: int | None = None) -> int:
        """Delete the oldest remote copies beyond the retention count."""
        keep = keep if keep is not None else (self.cfg.keep_last_uploads or 14)
        keys = sorted(k for k in self.list_remote()
                      if k.endswith(".mfenc"))
        excess = keys[:-keep] if len(keys) > keep else []
        user, secret = self.credentials
        removed = 0
        for key in excess:
            try:
                if self.cfg.provider == "s3":
                    _s3_request(self.cfg, "DELETE", key, b"", user, secret)
                else:
                    _webdav_request(self.cfg, "DELETE", key.rsplit("/", 1)[-1],
                                    b"", user, secret)
                removed += 1
            except OffsiteError as exc:
                log.warning("offsite prune skipped %s: %s", key, exc)
        return removed


def keys_path(data_dir: Path) -> Path:
    return Path(data_dir) / "offsite_keys.json"


def load_keys(data_dir: Path) -> dict:
    p = keys_path(data_dir)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_keys(data_dir: Path, keys: dict) -> None:
    p = keys_path(data_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(keys, indent=2), encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
