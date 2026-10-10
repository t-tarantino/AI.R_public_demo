"""Password hashing and session-token signing for the web app."""
from __future__ import annotations

import bcrypt
from itsdangerous import BadData, URLSafeTimedSerializer

from app.config import settings

# Sessions expire after 30 days (private internal app on personal phones).
SESSION_MAX_AGE_SECONDS = 30 * 24 * 3600

_serializer = URLSafeTimedSerializer(settings.secret_key, salt="air-session")


# bcrypt only looks at the first 72 BYTES of a password and raises on longer
# input in recent versions, so we truncate consistently when hashing AND
# verifying (same bytes both ways -> same result).
_BCRYPT_MAX_BYTES = 72


def _bcrypt_bytes(plain: str) -> bytes:
    return plain.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(_bcrypt_bytes(plain), bcrypt.gensalt()).decode("ascii")


def verify_password(plain: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_bcrypt_bytes(plain), password_hash.encode("ascii"))
    except ValueError:
        return False


def create_session_token(user_id: int) -> str:
    """Signed token stored in the session cookie."""
    return _serializer.dumps({"uid": user_id})


def read_session_token(token: str) -> int | None:
    """Return the user_id if the token is valid and not expired, else None."""
    try:
        data = _serializer.loads(token, max_age=SESSION_MAX_AGE_SECONDS)
    except BadData:
        # Covers a tampered, expired, OR simply corrupted/garbage cookie value
        # (BadSignature, SignatureExpired and BadPayload are all BadData): any of
        # them just means "no valid session", never an unhandled 500.
        return None
    return data.get("uid")