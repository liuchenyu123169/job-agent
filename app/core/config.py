import logging
import os

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# 模型配置已迁移到 app/core/model_config.yaml + model_provider.py
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-only-change-me")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))


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
