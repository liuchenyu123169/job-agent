from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user
from app.core.security import create_access_token, hash_password, verify_password
from app.db.crud import create_user, get_user_by_username
from app.schemas.user_schema import (
    CurrentUserResponse,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
)


router = APIRouter(prefix="/api/auth", tags=["Auth"])


def _build_token_response(user: dict) -> TokenResponse:
    access_token = create_access_token({"user_id": int(user["id"]), "username": user["username"]})
    return TokenResponse(
        access_token=access_token,
        user_id=int(user["id"]),
        username=str(user["username"]),
    )


@router.post("/register", response_model=TokenResponse)
def register(payload: RegisterRequest) -> TokenResponse:
    existing_user = get_user_by_username(payload.username)
    if existing_user is not None:
        raise HTTPException(status_code=400, detail="Username already exists")

    try:
        user = create_user(payload.username, hash_password(payload.password))
    except RuntimeError as exc:
        if "Username already exists" in str(exc):
            raise HTTPException(status_code=400, detail="Username already exists") from exc
        raise
    return _build_token_response(user)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest) -> TokenResponse:
    user = get_user_by_username(payload.username)
    if user is None or not user.get("password_hash") or not verify_password(payload.password, str(user["password_hash"])):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _build_token_response(user)


@router.get("/me", response_model=CurrentUserResponse)
def me(current_user: dict = Depends(get_current_user)) -> CurrentUserResponse:
    return CurrentUserResponse(id=int(current_user["id"]), username=str(current_user["username"]))
