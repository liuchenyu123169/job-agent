"""纯文本/JSON 处理工具，不依赖任何业务模块，可被任意层安全 import。"""

import json
from typing import Any


def clean_llm_json_output(text: str) -> str:
    """去除 LLM 输出中常见的 ```json ... ``` 包裹。"""
    cleaned = text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[len("```json"):]
    elif cleaned.startswith("```"):
        cleaned = cleaned[len("```"):]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-len("```")]
    return cleaned.strip()


def parse_llm_json_output(raw_output: str) -> dict[str, Any]:
    """安全解析 LLM JSON 输出，解析失败时返回 {"raw_output": raw_output}。"""
    try:
        return json.loads(clean_llm_json_output(raw_output))
    except json.JSONDecodeError:
        return {"raw_output": raw_output}
