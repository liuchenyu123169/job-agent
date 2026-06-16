"""SkillRegistry — 从 YAML 文件加载 Skill 配置，匹配用户意图。

设计考量：
  - YAML 驱动：新增 Skill 只需加一个文件，前端和后端自动感知。
  - 关键词匹配：简单高效，不需要 LLM 参与（节省 token 和延迟）。
  - 热重载：reload() 不重启服务即可更新 Skill 配置。
  - 前端可发现：to_api_list() 返回 Skill 列表，前端替代硬编码 resolveTools()。

匹配策略（优先级从高到低）：
  1. 关键词命中数量最多
  2. 命中数相同时，skill 在文件系统中的顺序
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

SKILLS_DIR = Path(__file__).resolve().parent


@dataclass
class Skill:
    """单个 Skill 配置。"""
    name: str
    description: str
    keywords: list[str] = field(default_factory=list)
    mode: str = "coordinator"        # fast | react | coordinator
    sub_agents: list[str] = field(default_factory=list)  # Coordinator 模式下委派的子 Agent
    tools: list[str] = field(default_factory=list)        # fast 模式下直接执行的工具

    @classmethod
    def from_yaml(cls, filepath: Path) -> "Skill | None":
        """从 YAML 文件加载一个 Skill。格式错误时返回 None。"""
        try:
            raw = yaml.safe_load(filepath.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                logger.warning("Skill %s 格式错误：应为 YAML 字典", filepath.name)
                return None
            return cls(
                name=raw.get("name", filepath.stem),
                description=raw.get("description", ""),
                keywords=[str(k).lower() for k in raw.get("keywords", [])],
                mode=raw.get("mode", "coordinator"),
                sub_agents=raw.get("sub_agents", []),
                tools=raw.get("tools", []),
            )
        except yaml.YAMLError as exc:
            logger.error("Skill %s 解析失败: %s", filepath.name, exc)
            return None

    def match_score(self, text: str) -> int:
        """计算文本与 Skill 的匹配分数（= 命中的关键词数量）。"""
        t = text.lower()
        return sum(1 for kw in self.keywords if kw in t)

    def to_api_dict(self) -> dict[str, Any]:
        """返回给前端的 Skill 摘要。"""
        return {
            "name": self.name,
            "description": self.description,
            "keywords": self.keywords,
            "mode": self.mode,
            "sub_agents": self.sub_agents,
            "tools": self.tools,
        }


class SkillRegistry:
    """Skill 注册中心 — 加载 YAML、匹配用户意图。

    用法:
        registry = SkillRegistry()
        skill = registry.match("帮我全面备战字节后端岗")
        if skill:
            print(f"命中: {skill.name} → mode={skill.mode}")
    """

    def __init__(self, skills_dir: Path | None = None):
        self._dir = Path(skills_dir) if skills_dir else SKILLS_DIR
        self._skills: list[Skill] = []
        self._load_all()

    def _load_all(self) -> None:
        """加载所有 *.yaml 文件（跳过 __init__.py 所在目录的特殊文件）。"""
        self._skills.clear()
        if not self._dir.is_dir():
            logger.warning("SkillRegistry 目录不存在: %s", self._dir)
            return
        for fpath in sorted(self._dir.glob("*.yaml")):
            skill = Skill.from_yaml(fpath)
            if skill:
                self._skills.append(skill)
                logger.info("SkillRegistry 已加载: '%s' (%d 关键词)", skill.name, len(skill.keywords))

    def match(self, text: str, min_score: int = 1) -> Skill | None:
        """根据用户输入文本匹配最合适的 Skill。

        Args:
            text: 用户输入（如 "帮我全面备战这个岗位"）
            min_score: 最低匹配分数（至少命中 1 个关键词）

        Returns:
            匹配分数最高的 Skill，无匹配时返回 None。
        """
        best_skill: Skill | None = None
        best_score = min_score - 1
        for skill in self._skills:
            score = skill.match_score(text)
            if score > best_score:
                best_score = score
                best_skill = skill
        return best_skill

    def list_all(self) -> list[Skill]:
        """返回所有已加载的 Skill。"""
        return list(self._skills)

    def to_api_list(self) -> list[dict[str, Any]]:
        """返回给前端的所有 Skill 摘要。"""
        return [s.to_api_dict() for s in self._skills]

    def reload(self) -> None:
        """热重载：重新读取文件系统中的所有 YAML 文件。"""
        logger.info("SkillRegistry 热重载中...")
        self._load_all()


# 全局单例
skill_registry = SkillRegistry()
