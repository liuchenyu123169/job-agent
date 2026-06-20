"""混合意图分类器 — 关键词优先 + 嵌入 fallback。

工作原理：
  1. 启动时：用 embedding-3 对所有 Skill 的 name+description+keywords 生成参考向量
  2. 运行时：先关键词匹配（快，~0ms）
  3. 关键词不够 → 嵌入余弦相似度匹配（~150ms，一次 embedding-3 HTTP 调用）
  4. 嵌入不够 → 返回空，Coordinator ReAct 兜底

零新依赖：复用已有的 EmbeddingClient（embedding-3 模型）。
"""

import logging
from typing import Any

import numpy as np

from app.rag.embedding import EmbeddingClient

logger = logging.getLogger(__name__)

# ── 阈值 ──
KEYWORD_MIN_SCORE = 1          # 关键词总分 < 1（即 0）才激活 embedding fallback
EMBEDDING_CONFIDENCE = 0.65    # 余弦相似度 ≥ 0.65 才路由
EMBEDDING_TOP_N = 3            # 最多返回 Top N 个匹配 skill

# ── 预计算的参考向量（启动时构建） ──
_skill_embeddings: dict[str, list[float]] = {}    # skill_name → embedding vector
_embedding_client: EmbeddingClient | None = None


def _get_client() -> EmbeddingClient:
    global _embedding_client
    if _embedding_client is None:
        _embedding_client = EmbeddingClient()
    return _embedding_client


def build_skill_embeddings(skills: list[Any]) -> None:
    """启动时调用：为所有 Skill 生成参考 embedding 向量。

    每个 Skill 的表示文本 = name + "：" + description + "。相关术语：" + keywords

    Args:
        skills: Skill 对象列表（需要有 .name, .description, .keywords 属性）
    """
    global _skill_embeddings
    client = _get_client()

    texts: list[str] = []
    names: list[str] = []
    for skill in skills:
        text = f"{skill.name}：{skill.description}。相关术语：{'，'.join(skill.keywords)}"
        texts.append(text)
        names.append(skill.name)

    if not texts:
        logger.warning("[IntentClassifier] 无 Skill 可供嵌入")
        return

    embeddings = client.embed_texts(texts)
    for name, emb in zip(names, embeddings):
        _skill_embeddings[name] = emb
    logger.info("[IntentClassifier] 已构建 %d 个 Skill 参考嵌入向量", len(_skill_embeddings))


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """两个向量之间的余弦相似度。"""
    a_np = np.array(a)
    b_np = np.array(b)
    dot = np.dot(a_np, b_np)
    norm_a = np.linalg.norm(a_np)
    norm_b = np.linalg.norm(b_np)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


def classify_embedding(text: str, skills: list[Any]) -> list[tuple[Any, float]]:
    """语义意图分类：嵌入用户输入 → 与所有 Skill 向量计算余弦相似度。

    Args:
        text: 用户输入文本
        skills: Skill 对象列表

    Returns:
        [(skill, confidence), ...] 按置信度降序，仅返回 ≥ EMBEDDING_CONFIDENCE 的结果。
        空列表表示未匹配到任何 Skill。
    """
    if not _skill_embeddings:
        logger.warning("[IntentClassifier] 无参考嵌入向量，回退到 Coordinator")
        return []

    client = _get_client()
    query_vec = client.embed_query(text)

    name_to_skill = {s.name: s for s in skills}
    scored: list[tuple[Any, float]] = []
    for skill in skills:
        ref_vec = _skill_embeddings.get(skill.name)
        if ref_vec is None:
            continue
        sim = _cosine_similarity(query_vec, ref_vec)
        if sim >= EMBEDDING_CONFIDENCE:
            scored.append((skill, sim))

    scored.sort(key=lambda x: x[1], reverse=True)
    result = scored[:EMBEDDING_TOP_N]

    if result:
        logger.info(
            "[IntentClassifier] 嵌入匹配: %s",
            ", ".join(f"{s.name}({c:.3f})" for s, c in result),
        )
    else:
        logger.info("[IntentClassifier] 嵌入匹配置信度不足，委派 Coordinator")

    return result
