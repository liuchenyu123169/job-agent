from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import JWT_ALGORITHM, JWT_EXPIRE_MINUTES, JWT_SECRET_KEY


class DuplicateUserError(Exception):
    """用户名重复异常。"""


pwd_context = CryptContext(schemes=["bcrypt"], deprecated=[])


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return pwd_context.verify(plain_password, password_hash)


def create_access_token(data: dict[str, Any]) -> str:
    to_encode = data.copy()
    now = datetime.now(UTC)
    to_encode.update({
        "sub": str(data.get("user_id", "")),
        "iat": now,
        "exp": now + timedelta(minutes=JWT_EXPIRE_MINUTES),
    })
    return jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        if not isinstance(payload, dict):
            raise ValueError("Invalid token payload")
        return payload
    except JWTError as exc:
        raise ValueError("Invalid or expired token") from exc
