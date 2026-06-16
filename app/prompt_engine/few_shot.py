"""FewShotStore — YAML 示例库的存取与检索。

设计考量：
  - YAML 格式：人类可读写，非技术同事也能贡献示例。
  - 场景维度：每个 YAML 文件名 = 场景标签（如 "match_analyze"）。
    一个场景下可以有多个示例，每个示例有 input/output 字段。
  - 选择策略：目前用前 N 条（简单），后期可加语义相似度检索。
  - 热重载：reload() 不重启服务即可更新示例库。
"""

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

FEW_SHOTS_DIR = Path(__file__).resolve().parents[1] / "prompts" / "few_shots"


class FewShotStore:
    """Few-shot 示例存储与检索。

    文件结构：
        app/prompts/few_shots/
          match_analyze.yaml      ← 场景标签 = 文件名
          interview_questions.yaml

    YAML 格式：
        - input:
            resume_content: "3年Java开发..."
            job_jd: "要求精通Spring Boot..."
          output:
            match_score: 85
            advantages: ["Spring Boot经验匹配"]
            weaknesses: ["缺少分布式经验"]
            suggestions: ["补充微服务项目"]
    """

    def __init__(self, store_dir: Path | None = None):
        self._dir = Path(store_dir) if store_dir else FEW_SHOTS_DIR
        self._cache: dict[str, list[dict[str, Any]]] = {}
        self._load_all()

    def _load_all(self) -> None:
        """加载所有 *.yaml 文件到内存缓存。"""
        self._cache.clear()
        if not self._dir.is_dir():
            logger.warning("FewShotStore 目录不存在: %s，将不启用 few-shot", self._dir)
            return
        for fpath in sorted(self._dir.glob("*.yaml")):
            scene = fpath.stem  # 文件名（不含扩展名）= 场景标签
            try:
                raw = yaml.safe_load(fpath.read_text(encoding="utf-8"))
                if not isinstance(raw, list):
                    logger.warning("FewShot %s 格式错误：应为 YAML 列表，实际为 %s", fpath, type(raw).__name__)
                    continue
                # 校验每条示例有 input/output
                valid = [item for item in raw if isinstance(item, dict) and "input" in item and "output" in item]
                if len(valid) < len(raw):
                    logger.warning("FewShot %s：%d 条缺少 input/output 字段，已跳过", fpath, len(raw) - len(valid))
                self._cache[scene] = valid
                logger.info("FewShotStore loaded '%s': %d examples", scene, len(valid))
            except yaml.YAMLError as exc:
                logger.error("FewShotStore 解析失败 %s: %s", fpath, exc)

    def get(self, scene: str, max_items: int = 3) -> list[dict[str, Any]]:
        """获取指定场景的 few-shot 示例。

        Args:
            scene: 场景标签（YAML 文件名）
            max_items: 最多返回几条示例

        Returns:
            [{"input": {...}, "output": {...}}, ...]
        """
        examples = self._cache.get(scene, [])
        return examples[:max_items]

    def list_scenes(self) -> list[str]:
        """列出所有已加载的场景标签。"""
        return sorted(self._cache.keys())

    def add(self, scene: str, example: dict[str, Any]) -> None:
        """运行时添加一条示例（不立即写盘）。"""
        if "input" not in example or "output" not in example:
            raise ValueError("Few-shot example must have 'input' and 'output' keys")
        self._cache.setdefault(scene, []).append(example)
        logger.info("FewShotStore '%s' 新增示例（内存），当前共 %d 条", scene, len(self._cache[scene]))
