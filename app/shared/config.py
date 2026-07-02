import logging
import os

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# 模型配置已迁移到 app/core/model_config.yaml + model_provider.py
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-only-change-me")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))

# ── 博查公开搜索 ──
BOCHA_API_KEY = os.getenv("BOCHA_API_KEY", "")
BOCHA_BASE_URL = os.getenv("BOCHA_BASE_URL", "https://api.bocha.cn")
BOCHA_TIMEOUT_SECONDS = int(os.getenv("BOCHA_TIMEOUT_SECONDS", "10"))
BOCHA_SEARCH_PATH = os.getenv("BOCHA_SEARCH_PATH", "/v1/web-search")

# ── 八爪鱼页面采集 ──
BAZHUA_API_KEY = os.getenv("BAZHUA_API_KEY", "")
BAZHUA_BASE_URL = os.getenv("BAZHUA_BASE_URL", "https://mcp.bazhuayu.com")
BAZHUA_TIMEOUT_SECONDS = int(os.getenv("BAZHUA_TIMEOUT_SECONDS", "30"))


def check_jwt_secret() -> None:
    """Startup check: warn if JWT_SECRET_KEY is still the default value."""
    if JWT_SECRET_KEY == "dev-only-change-me":
        logger.warning(
            "JWT_SECRET_KEY is still set to 'dev-only-change-me'. "
            "Set JWT_SECRET_KEY in your .env file for production use."
        )
        print(
            "\n\033[93m[WARNING]\033[0m JWT_SECRET_KEY is still 'dev-only-change-me'. "
            "Please set JWT_SECRET_KEY in .env before deploying!\n",
            flush=True,
        )
