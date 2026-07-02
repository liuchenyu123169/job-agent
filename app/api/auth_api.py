from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user
from app.infrastructure.security import DuplicateUserError, create_access_token, hash_password, verify_password
from app.infrastructure.db.crud import create_user, get_user_by_username
from app.shared.schemas.user_schema import (
    CurrentUserResponse,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
)


router = APIRouter(prefix="/api/auth", tags=["Auth"])


def _build_token_response(user: dict) -> TokenResponse:
    is_admin = bool(user.get("is_admin", False))
    access_token = create_access_token({
        "user_id": int(user["id"]),
        "username": user["username"],
        "is_admin": is_admin,
    })
    return TokenResponse(
        access_token=access_token,
        user_id=int(user["id"]),
        username=str(user["username"]),
        is_admin=is_admin,
    )


@router.post("/register", response_model=TokenResponse)
def register(payload: RegisterRequest) -> TokenResponse:
    try:
        user = create_user(payload.username, hash_password(payload.password))
    except DuplicateUserError:
        raise HTTPException(status_code=400, detail="该用户名已被注册")
    return _build_token_response(user)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest) -> TokenResponse:
    user = get_user_by_username(payload.username)
    if user is None or not user.get("password_hash") or not verify_password(payload.password, str(user["password_hash"])):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _build_token_response(user)


@router.get("/me", response_model=CurrentUserResponse)
def me(current_user: dict = Depends(get_current_user)) -> CurrentUserResponse:
    return CurrentUserResponse(
        id=int(current_user["id"]),
        username=str(current_user["username"]),
        is_admin=bool(current_user.get("is_admin", False)),
    )
