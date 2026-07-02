from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from app.infrastructure.security import decode_access_token
from app.infrastructure.db.crud import get_user_by_id


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def get_current_user(token: str = Depends(oauth2_scheme)) -> dict[str, Any]:
    try:
        payload = decode_access_token(token)
    except ValueError as exc:
        msg = str(exc)
        if msg == "token_expired":
            detail = "登录已过期，请重新登录"
        else:
            detail = "认证信息无效"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user_id = payload.get("user_id")
    if not isinstance(user_id, int):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="认证信息无效",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = get_user_by_id(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="该用户已不存在",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def get_admin_user(current_user: dict = Depends(get_current_user)) -> dict:
    """管理员专用依赖：非管理员返回 403。"""
    if not current_user.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限",
        )
    return current_user
