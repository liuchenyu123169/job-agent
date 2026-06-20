from pydantic import BaseModel, Field, field_validator


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def password_must_have_letter_and_digit(cls, v: str) -> str:
        import re
        if not re.search(r"[A-Za-z]", v):
            raise ValueError("密码需包含至少一个字母")
        if not re.search(r"\d", v):
            raise ValueError("密码需包含至少一个数字")
        return v


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    username: str
    is_admin: bool = False


class CurrentUserResponse(BaseModel):
    id: int
    username: str
    is_admin: bool = False
