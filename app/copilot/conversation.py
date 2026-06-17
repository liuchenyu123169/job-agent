"""ConversationManager — 对话消息持久化、加载、上下文窗口管理。

职责：
- 从 DB 加载历史消息，重建 LangChain BaseMessage 列表
- 将新消息批量保存到 DB（去重）
- 估算 token 数量（中文/英文自适应）
- 上下文窗口超限时自动摘要压缩
"""

import json
import logging
import re
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from app.db.crud import (
    create_conversation_message,
    delete_conversation_messages,
    get_conversation_messages,
    update_session_messages_summary,
)

logger = logging.getLogger(__name__)

# ── Token 估算 ──

_CHINESE_RE = re.compile(r"[一-鿿　-〿＀-￯]")

# 上下文窗口阈值（保守：给 tool 结果和 LLM 回复留余量）
MAX_TOKENS = 6000
# 压缩后至少保留的最近消息对数
MIN_RECENT_PAIRS = 4


def estimate_tokens(text: str) -> int:
    """粗略估算 token 数（GLM tokenizer 不可本地获取，使用字符级启发式）。

    中文约 1 token ≈ 2 字符，英文 1 token ≈ 4 字符。
    """
    if not text:
        return 0
    chinese = len(_CHINESE_RE.findall(text))
    ascii_chars = len(text) - chinese
    return int(chinese * 0.5 + ascii_chars * 0.25)


def estimate_messages_tokens(messages: list[BaseMessage]) -> int:
    """估算消息列表的总 token 数。"""
    total = 0
    for msg in messages:
        content = str(msg.content) if msg.content else ""
        total += estimate_tokens(content)
        # tool_calls 也占 token
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                total += estimate_tokens(str(tc.get("name", "")))
                total += estimate_tokens(str(tc.get("args", "")))
                total += estimate_tokens(str(tc.get("id", "")))
        if isinstance(msg, ToolMessage):
            total += estimate_tokens(str(msg.tool_call_id))
            total += estimate_tokens(str(msg.name or ""))
    return total


# ── 消息序列化/反序列化 ──


def _message_to_db(
    session_id: int,
    user_id: int,
    msg: BaseMessage,
) -> int | None:
    """将一条 LangChain BaseMessage 写入 DB。"""
    role: str
    content: str | None = None
    tool_calls_json: str | None = None
    tool_call_id: str | None = None
    tool_name: str | None = None

    if isinstance(msg, HumanMessage):
        role = "user"
        content = str(msg.content) if msg.content else ""
    elif isinstance(msg, AIMessage):
        role = "assistant"
        content = str(msg.content) if msg.content else ""
        if msg.tool_calls:
            tool_calls_json = json.dumps(msg.tool_calls, ensure_ascii=False)
    elif isinstance(msg, ToolMessage):
        role = "tool"
        content = str(msg.content) if msg.content else ""
        tool_call_id = str(msg.tool_call_id) if msg.tool_call_id else ""
        tool_name = str(msg.name) if msg.name else ""
    elif isinstance(msg, SystemMessage):
        role = "system"
        content = str(msg.content) if msg.content else ""
    else:
        role = type(msg).__name__.lower()
        content = str(msg.content) if msg.content else ""

    return create_conversation_message(
        session_id=session_id,
        user_id=user_id,
        role=role,
        content=content,
        tool_calls_json=tool_calls_json,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
    )


def _db_to_message(row: dict[str, Any]) -> BaseMessage:
    """将 DB 行还原为 BaseMessage。"""
    role = str(row.get("role") or "user")
    content = str(row.get("content") or "")

    if role == "user":
        return HumanMessage(content=content)
    elif role == "assistant":
        tool_calls_json = row.get("tool_calls_json")
        tool_calls = None
        if tool_calls_json:
            try:
                tool_calls = json.loads(tool_calls_json)
            except json.JSONDecodeError:
                pass
        return AIMessage(content=content, tool_calls=tool_calls or [])
    elif role == "tool":
        return ToolMessage(
            content=content,
            tool_call_id=str(row.get("tool_call_id") or ""),
            name=str(row.get("tool_name") or ""),
        )
    elif role == "system":
        return SystemMessage(content=content)
    else:
        return HumanMessage(content=content)


# ── ConversationManager ──


class ConversationManager:
    """对话管理器：加载历史、保存消息、管理上下文窗口。"""

    def load_history(
        self,
        session_id: int,
        user_id: int,
        system_prompt: str = "",
    ) -> list[BaseMessage]:
        """从 DB 加载会话的所有历史消息。

        Args:
            session_id: 会话 ID
            user_id: 用户 ID
            system_prompt: 系统提示词（不作为消息保存，但放在消息列表最前面）

        Returns:
            BaseMessage 列表，按时间升序。第一条为 SystemMessage（如果 system_prompt 非空）。
        """
        rows = get_conversation_messages(session_id, user_id)
        messages: list[BaseMessage] = []

        # 系统提示词永远在第一位，不存 DB
        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))

        for row in rows:
            try:
                msg = _db_to_message(row)
                messages.append(msg)
            except Exception as exc:
                logger.warning("Failed to deserialize message id=%s: %s", row.get("id"), exc)

        logger.info(
            "[ConversationManager] loaded %d messages from session %d (total %d with system)",
            len(rows), session_id, len(messages),
        )
        return messages

    def save_messages(
        self,
        session_id: int,
        user_id: int,
        messages: list[BaseMessage],
        skip_system: bool = True,
    ) -> int:
        """批量保存新消息到 DB。

        Args:
            session_id: 会话 ID
            user_id: 用户 ID
            messages: 消息列表
            skip_system: 是否跳过 SystemMessage（系统提示词不持久化）

        Returns:
            实际保存的消息条数（含被去重跳过的）。
        """
        saved = 0
        for msg in messages:
            if skip_system and isinstance(msg, SystemMessage):
                continue
            _message_to_db(session_id, user_id, msg)
            saved += 1
        logger.info("[ConversationManager] saved %d messages to session %d", saved, session_id)
        return saved

    def manage_window(
        self,
        messages: list[BaseMessage],
        max_tokens: int = MAX_TOKENS,
    ) -> tuple[list[BaseMessage], str | None]:
        """管理上下文窗口：估算 token，超限时压缩旧消息。

        策略：
        1. 计算当前消息列表 token 总数
        2. 未超限 → 直接返回
        3. 超限 → 保留最近 MIN_RECENT_PAIRS 对 user-assistant 消息（含它们之间的 ToolMessage）
           更早的消息合并成一条摘要 SystemMessage

        Args:
            messages: 完整消息列表（第一条通常是 SystemMessage）
            max_tokens: token 上限

        Returns:
            (truncated_messages, summary_text_or_None)
        """
        total = estimate_messages_tokens(messages)
        if total <= max_tokens:
            return messages, None

        # SystemMessage 始终保留（通常在第一位置）
        system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
        non_system = [m for m in messages if not isinstance(m, SystemMessage)]

        # 从后往前找最近 MIN_RECENT_PAIRS 对 user-assistant
        # 一对 = HumanMessage → (AIMessage + 可能多个 ToolMessage) → 下一个 HumanMessage
        pairs_found = 0
        cutoff_idx = len(non_system)
        seen_human = False
        for i in range(len(non_system) - 1, -1, -1):
            msg = non_system[i]
            if isinstance(msg, HumanMessage):
                if seen_human:
                    pairs_found += 1
                seen_human = True
            if pairs_found >= MIN_RECENT_PAIRS:
                cutoff_idx = i
                break

        # 分割：cutoff_idx 之前的旧消息 → 摘要；之后的保留
        old_messages = non_system[:cutoff_idx]
        recent_messages = non_system[cutoff_idx:]

        if not old_messages:
            return system_msgs + recent_messages, None

        # 从旧消息提取摘要文本（不做 LLM 摘要，用简单规则提取关键信息）
        summary_text = self._build_summary(old_messages)

        result = list(system_msgs)
        if summary_text:
            result.append(SystemMessage(
                content=f"[会话历史摘要]\n以下是你和用户之前的对话要点，请基于这些上下文理解用户当前的问题：\n\n{summary_text}"
            ))

        result.extend(recent_messages)
        logger.info(
            "[ConversationManager] window truncated: %d → %d messages (summary: %d chars)",
            len(messages), len(result), len(summary_text or ""),
        )
        return result, summary_text

    def _build_summary(self, messages: list[BaseMessage]) -> str:
        """从旧消息提取摘要（纯规则，不调 LLM）。

        提取每对 user-assistant 对话的关键内容。
        """
        pairs: list[str] = []
        current_user = ""
        for msg in messages:
            if isinstance(msg, HumanMessage):
                content = str(msg.content or "").strip()
                if content:
                    current_user = content[:200]
            elif isinstance(msg, AIMessage):
                content = str(msg.content or "").strip()
                if content and current_user:
                    # 取 AI 回复的前 150 字作为摘要
                    summary = content[:150].replace("\n", " ")
                    pairs.append(f"用户：{current_user[:100]}\nAI：{summary}")
                    current_user = ""
                elif content and not current_user:
                    # AI 回复但没有对应用户消息（可能是工具调用结果触发的）
                    summary = content[:150].replace("\n", " ")
                    pairs.append(f"AI：{summary}")

        if not pairs:
            return ""

        return "\n\n".join(pairs[-10:])  # 最多保留 10 对

    def clear_session(self, session_id: int, user_id: int) -> int:
        """清除会话的所有消息。"""
        return delete_conversation_messages(session_id, user_id)

    def save_summary(
        self,
        session_id: int,
        user_id: int,
        summary: str | None,
    ) -> None:
        """保存上下文摘要到 copilot_session。"""
        update_session_messages_summary(session_id, user_id, summary)


# 单例
conversation_manager = ConversationManager()
