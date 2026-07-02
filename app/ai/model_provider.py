"""模型提供层 — 多模型实例管理、按任务路由、重试、并发控制。

用法:
    from app.ai.model_provider import model_provider
    result = model_provider.invoke("prompt", model_key="primary")
    async for token in model_provider.stream("prompt", model_key="primary"):
        ...
"""

import asyncio
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, AsyncGenerator

import yaml
from langchain_core.messages import AIMessage, BaseMessage
from langchain_openai import ChatOpenAI

from app.shared.observability import StructuredLogger, metrics
from app.shared.observability.tracer import add_trace_metadata

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parent / "model_config.yaml"


def _resolve_env(value: str) -> str:
    """替换字符串中的 ${ENV_VAR} 占位符。"""

    def _replace(match: re.Match) -> str:
        var = match.group(1)
        return os.getenv(var, "")

    return re.sub(r"\$\{(\w+)\}", _replace, value)


class ModelProvider:
    """多模型提供者 — 懒加载 LLM 实例，按 key 路由，统一管理并发和重试。"""

    def __init__(self, config_path: Path | None = None) -> None:
        self._config_path = config_path or CONFIG_PATH
        self._instances: dict[str, ChatOpenAI] = {}
        self._config: dict[str, Any] = {}
        self._semaphore: asyncio.Semaphore | None = None
        self._load_config()

    # ── 配置加载 ──

    def _load_config(self) -> None:
        if not self._config_path.exists():
            logger.warning("model_config.yaml 不存在: %s，使用默认配置", self._config_path)
            self._config = self._default_config()
            return

        with open(self._config_path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        self._config = raw or {}
        models_cfg = self._config.get("models", {})
        logger.info(
            "ModelProvider: 已加载 %d 个模型定义，default=%s",
            len(models_cfg),
            self._config.get("default", "primary"),
        )

    @staticmethod
    def _default_config() -> dict[str, Any]:
        return {
            "models": {
                "primary": {
                    "provider": "zhipu",
                    "model": os.getenv("LLM_MODEL") or os.getenv("MODEL_NAME", "glm-4-flash"),
                    "base_url": os.getenv("ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/"),
                    "api_key_env": "ZHIPU_API_KEY",
                    "max_tokens": 4096,
                    "temperature": 0.7,
                }
            },
            "default": "primary",
            "concurrency": {"max_concurrent": 5},
            "retry": {"max_attempts": 3, "backoff_base": 1.0, "backoff_max": 30.0},
        }

    # ── 实例获取 ──

    def _get_model_config(self, model_key: str | None = None) -> dict[str, Any]:
        key = model_key or self._config.get("default", "primary")
        models = self._config.get("models", {})
        if key not in models:
            logger.warning("model_key=%s 不存在，回退到 primary", key)
            key = "primary"
        return models.get(key, models.get("primary", {}))

    def get_llm(self, model_key: str | None = None) -> ChatOpenAI:
        key = model_key or self._config.get("default", "primary")
        if key not in self._instances:
            cfg = self._get_model_config(key)
            api_key = os.getenv(cfg.get("api_key_env", ""), "")
            if not api_key:
                raise RuntimeError(
                    f"模型 '{key}' 需要环境变量 {cfg.get('api_key_env')}，"
                    f"请检查 .env 文件"
                )
            self._instances[key] = ChatOpenAI(
                api_key=api_key,
                base_url=_resolve_env(cfg.get("base_url", "")),
                model=cfg.get("model", ""),
                temperature=cfg.get("temperature", 0.7),
                max_tokens=cfg.get("max_tokens", 4096),
            )
            logger.info("ModelProvider: 初始化 %s → %s", key, cfg.get("model"))
        return self._instances[key]

    def get_model_name(self, model_key: str | None = None) -> str:
        return self._get_model_config(model_key).get("model", "unknown")

    # ── 并发控制 ──

    @property
    def semaphore(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            limit = self._config.get("concurrency", {}).get("max_concurrent", 5)
            self._semaphore = asyncio.Semaphore(limit)
        return self._semaphore

    # ── 重试配置 ──

    def _retry_config(self) -> dict[str, Any]:
        return self._config.get("retry", {"max_attempts": 3, "backoff_base": 1.0, "backoff_max": 30.0})

    # ── 同步调用 ──

    def invoke(self, prompt: str, *, model_key: str | None = None) -> str:
        """同步 LLM 调用（带重试和指标记录）。"""
        t0 = time.monotonic()
        llm = self.get_llm(model_key)
        model_name = self.get_model_name(model_key)

        retry_cfg = self._retry_config()
        last_error: Exception | None = None

        for attempt in range(retry_cfg["max_attempts"]):
            try:
                response = llm.invoke(prompt)
                break
            except Exception as exc:
                last_error = exc
                if attempt < retry_cfg["max_attempts"] - 1:
                    wait = min(
                        retry_cfg["backoff_base"] * (2**attempt),
                        retry_cfg["backoff_max"],
                    )
                    logger.warning(
                        "LLM 调用失败 (attempt %d/%d, model=%s): %s，%0.1fs 后重试",
                        attempt + 1,
                        retry_cfg["max_attempts"],
                        model_name,
                        exc,
                        wait,
                    )
                    time.sleep(wait)
                    # 最后一次重试切换 fallback
                    if attempt == retry_cfg["max_attempts"] - 2:
                        fallback = self._config.get("models", {}).get("fallback")
                        if fallback:
                            logger.info("切换到 fallback 模型")
                            llm = self.get_llm("fallback")
                            model_name = self.get_model_name("fallback")
                else:
                    raise last_error

        duration_ms = (time.monotonic() - t0) * 1000
        content = str(response.content)

        # token 用量
        meta = getattr(response, "response_metadata", {}) or {}
        usage = meta.get("token_usage", {})
        tokens_in = usage.get("prompt_tokens", 0) or len(prompt) // 3
        tokens_out = usage.get("completion_tokens", 0) or len(content) // 3

        add_trace_metadata("model", model_name)
        add_trace_metadata("prompt_chars", len(prompt))
        add_trace_metadata("response_chars", len(content))
        add_trace_metadata("tokens_in", tokens_in)
        add_trace_metadata("tokens_out", tokens_out)
        add_trace_metadata("duration_ms", duration_ms)

        StructuredLogger.log_llm_call(
            model=model_name,
            duration_ms=duration_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            prompt_chars=len(prompt),
            response_chars=len(content),
        )
        metrics.record_llm_call(
            model=model_name,
            duration_ms=duration_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )
        return content

    # ── 异步流式调用 ──

    async def stream(
        self, prompt: str, *, model_key: str | None = None
    ) -> AsyncGenerator[str, None]:
        """异步流式 LLM 调用（带并发控制和指标记录）。"""
        t0 = time.monotonic()
        llm = self.get_llm(model_key)
        model_name = self.get_model_name(model_key)

        total_chars = 0
        async with self.semaphore:
            async for chunk in llm.astream(prompt):
                content = chunk.content
                if isinstance(content, str) and content:
                    total_chars += len(content)
                    yield content

        duration_ms = (time.monotonic() - t0) * 1000
        tokens_in = len(prompt) // 3
        tokens_out = total_chars // 3

        add_trace_metadata("model", model_name)
        add_trace_metadata("prompt_chars", len(prompt))
        add_trace_metadata("response_chars", total_chars)
        add_trace_metadata("duration_ms", duration_ms)

        metrics.record_llm_call(
            model=model_name,
            duration_ms=duration_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )

    # ── 带工具的调用（Coordinator 用） ──

    def bind_tools(
        self,
        tool_definitions: list[dict[str, Any]],
        model_key: str | None = None,
    ) -> ChatOpenAI:
        """将工具定义绑定到 LLM 实例，返回支持 function-calling 的模型。"""
        llm = self.get_llm(model_key)
        langchain_tools = []
        for td in tool_definitions:
            func = td.get("function", td)
            langchain_tools.append({
                "name": func["name"],
                "description": func.get("description", ""),
                "parameters": func.get("parameters", {"type": "object", "properties": {}}),
            })
        return llm.bind_tools(langchain_tools)

    def invoke_with_tools(
        self,
        messages: list[BaseMessage],
        tool_definitions: list[dict[str, Any]],
        *,
        model_key: str | None = None,
    ) -> AIMessage:
        """带工具调用的 LLM 请求（同步，Coordinator 用）。"""
        t0 = time.monotonic()
        llm_with_tools = self.bind_tools(tool_definitions, model_key)
        response = llm_with_tools.invoke(messages)
        duration_ms = (time.monotonic() - t0) * 1000

        model_name = self.get_model_name(model_key)
        meta = getattr(response, "response_metadata", {}) or {}
        usage = meta.get("token_usage", {})
        total_chars = sum(len(str(m.content or "")) for m in messages)
        tokens_in = usage.get("prompt_tokens", 0) or total_chars // 3
        tokens_out = usage.get("completion_tokens", 0) or len(str(response.content or "")) // 3

        add_trace_metadata("model", model_name)
        add_trace_metadata("tokens_in", tokens_in)
        add_trace_metadata("tokens_out", tokens_out)
        add_trace_metadata("duration_ms", duration_ms)
        metrics.record_llm_call(
            model=model_name,
            duration_ms=duration_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )
        return response


# 全局单例
model_provider = ModelProvider()
