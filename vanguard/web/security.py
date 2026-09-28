"""Password hashing and signed session tokens (standard HS256 JWTs) using only the standard library."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

PBKDF2_ITERATIONS = 240_000
TOKEN_TTL_SECONDS = int(os.getenv("VANGUARD_SESSION_HOURS", "12")) * 3600


def hash_password(password: str) -> str:
    if len(password) < 10:
        raise ValueError("password must be at least 10 characters")
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt, digest = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iters))
        return hmac.compare_digest(dk.hex(), digest)
    except (ValueError, TypeError):
        return False


def _secret() -> bytes:
    env = os.getenv("VANGUARD_JWT_SECRET")
    if env:
        return env.encode()
    path = Path(os.getenv("VANGUARD_DB", "data/vanguard.db")).parent / "jwt_secret"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_hex(32), encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass
    return path.read_text(encoding="utf-8").strip().encode()


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def make_token(user_id: int, role: str, ttl: int = TOKEN_TTL_SECONDS) -> str:
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    now = int(time.time())
    payload = _b64(json.dumps({"sub": str(user_id), "role": role, "iat": now, "exp": now + ttl}).encode())
    sig = _b64(hmac.new(_secret(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}"


def read_token(token: str) -> dict | None:
    try:
        header, payload, sig = token.split(".")
        expected = _b64(hmac.new(_secret(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        if json.loads(_unb64(header)).get("alg") != "HS256":
            return None
        data = json.loads(_unb64(payload))
        if data.get("exp", 0) < time.time():
            return None
        return data
    except (ValueError, json.JSONDecodeError):
        return None


def generate_password() -> str:
    return secrets.token_urlsafe(12)
