"""Core — [COMPAT FORWARD] 所有实现已拆分到 shared / ai / infrastructure。

此文件仅作为兼容转发层保留。新代码请直接导入新位置：
  config / constants → app.shared
  llm / model_provider → app.ai
  security → app.infrastructure
后续阶段将删除此目录。
"""
from app.shared.config import (
    BAZHUA_API_KEY, BAZHUA_BASE_URL, BAZHUA_TIMEOUT_SECONDS,
    BOCHA_API_KEY, BOCHA_BASE_URL, BOCHA_SEARCH_PATH, BOCHA_TIMEOUT_SECONDS,
    JWT_ALGORITHM, JWT_EXPIRE_MINUTES, JWT_SECRET_KEY,
)
from app.shared.constants import DEFAULT_USER_ID
from app.ai.llm import invoke_llm, invoke_llm_with_tools, stream_llm
from app.ai.model_provider import ModelProvider, model_provider
from app.infrastructure.security import (
    DuplicateUserError, create_access_token, decode_access_token,
    hash_password, verify_password,
)
