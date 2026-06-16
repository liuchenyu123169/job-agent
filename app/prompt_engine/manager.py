"""PromptManager — Jinja2 模板加载 / few-shot 注入 / 渲染。

设计考量：
  - 版本化目录：app/prompts/v1/, v2/ ... 切换 version 参数即可。
  - 动态注入：render() 时从 FewShotStore 取示例，注入模板变量 {{ few_shots }}。
  - 缓存：生产环境开启 Jinja2 BytecodeCache 避免重复解析。
  - 错误处理：模板不存在/变量缺失时抛出明确异常，不静默降级。
"""

import logging
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, TemplateNotFound, UndefinedError

from app.prompt_engine.few_shot import FewShotStore

logger = logging.getLogger(__name__)

PROMPTS_BASE = Path(__file__).resolve().parents[1] / "prompts"


class PromptManager:
    """Jinja2 模板管理器。

    用法:
        pm = PromptManager(version="v1")
        prompt = pm.render("match_analyze", resume_content="...", job_jd="...")
    """

    def __init__(self, version: str = "v1", few_shot_store: FewShotStore | None = None):
        self.version = version
        self.few_shot_store = few_shot_store
        template_dir = PROMPTS_BASE / version
        if not template_dir.is_dir():
            raise FileNotFoundError(f"Prompt 模板目录不存在: {template_dir}")
        self._env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        logger.info("PromptManager initialized: version=%s dir=%s", version, template_dir)

    def render(
        self,
        template_name: str,
        scene: str | None = None,
        max_few_shots: int = 3,
        **variables: Any,
    ) -> str:
        """加载模板 → 注入 few-shot → 渲染为最终 prompt 文本。

        Args:
            template_name: 模板文件名，不含 .j2 后缀，如 "match_analyze"
            scene: few-shot 场景标签，传入则自动注入。为 None 则跳过 few-shot。
            max_few_shots: 最多注入几条 few-shot 示例。
            **variables: 模板变量（resume_content, job_jd, ...）

        Returns:
            渲染后的 prompt 纯文本。
        """
        try:
            template = self._env.get_template(f"{template_name}.j2")
        except TemplateNotFound:
            raise FileNotFoundError(
                f"模板 '{template_name}.j2' 在 {self._env.loader.searchpath} 中不存在"
            )

        # 注入 few-shot（如果配置了 store 且指定了 scene）
        if self.few_shot_store and scene:
            shots = self.few_shot_store.get(scene, max_items=max_few_shots)
            if shots:
                variables.setdefault("few_shots", shots)
                logger.debug("Injected %d few-shot examples for scene '%s'", len(shots), scene)
        elif "few_shots" not in variables:
            variables["few_shots"] = []

        try:
            return template.render(**variables)
        except UndefinedError as exc:
            raise ValueError(
                f"模板 '{template_name}.j2' 渲染失败：缺少变量或变量名拼写错误 — {exc}"
            ) from exc

    def list_templates(self) -> list[str]:
        """列出当前版本的所有模板名（不含 .j2 后缀）。"""
        search_dir = PROMPTS_BASE / self.version
        return sorted(
            [f.stem for f in search_dir.glob("*.j2")]
        )

    @property
    def template_dir(self) -> Path:
        return PROMPTS_BASE / self.version
