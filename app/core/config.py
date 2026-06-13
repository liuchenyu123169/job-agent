import os

from dotenv import load_dotenv


load_dotenv()

ZHIPU_BASE_URL = os.getenv("ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/")
MODEL_NAME = os.getenv("MODEL_NAME", "glm-4-flash")


def get_api_key() -> str:
    api_key = os.getenv("ZHIPU_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("ZHIPU_API_KEY or OPENAI_API_KEY is required")
    return api_key
