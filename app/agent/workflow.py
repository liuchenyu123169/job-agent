import logging
import re
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agent.common import parse_llm_json_output, read_prompt_template, save_success_task
from app.agent.state import AgentAnalyzeState
from app.core.llm import invoke_llm
from app.db.crud import get_job_by_id, get_resume_by_id
from app.rag.rag_service import search_knowledge


logger = logging.getLogger(__name__)

TECH_KEYWORDS = [
    "Spring Boot",
    "Spring Cloud",
    "LangChain",
    "LangGraph",
    "FastAPI",
    "MyBatis",
    "RocketMQ",
    "RabbitMQ",
    "Redisson",
    "Embedding",
    "Prompt",
    "Chroma",
    "Agent",
    "Redis",
    "MySQL",
    "Java",
    "JVM",
    "Spring",
    "Kafka",
    "Nacos",
    "Sentinel",
    "Seata",
    "Docker",
    "Nginx",
    "Linux",
    "RAG",
    "LLM",
    "Lua",
    "Python",
    "线程池",
    "多线程",
    "并发",
    "分布式锁",
    "事务",
    "索引",
    "B+树",
    "MVCC",
    "缓存穿透",
    "缓存击穿",
    "缓存雪崩",
    "缓存",
    "限流",
    "熔断",
    "降级",
    "分库分表",
    "消息队列",
    "幂等",
    "向量数据库",
    "锁",
]

BACKEND_KEYWORDS = {
    "Java",
    "JVM",
    "Spring",
    "Spring Boot",
    "MySQL",
    "Redis",
    "MyBatis",
    "线程池",
    "多线程",
    "并发",
    "锁",
    "分布式锁",
    "事务",
    "索引",
    "MVCC",
    "缓存",
    "消息队列",
    "RocketMQ",
    "Kafka",
    "RabbitMQ",
    "分库分表",
    "幂等",
    "限流",
}

AI_KEYWORDS = {
    "LangChain",
    "LangGraph",
    "RAG",
    "Agent",
    "Embedding",
    "Chroma",
    "LLM",
    "Prompt",
    "向量数据库",
}

GENERIC_TITLE_KEYWORDS = ("面试知识点", "基础", "底层结构详解")
CATEGORY_KEYWORDS = {
    "java": [
        "Java",
        "JVM",
        "线程池",
        "多线程",
        "并发",
        "synchronized",
        "ReentrantLock",
        "锁",
        "死锁",
        "乐观锁",
        "悲观锁",
    ],
    "mysql": [
        "MySQL",
        "索引",
        "B+树",
        "事务",
        "MVCC",
        "InnoDB",
        "binlog",
        "redo log",
        "undo log",
        "主从复制",
        "SQL",
        "慢查询",
    ],
    "redis": [
        "Redis",
        "缓存",
        "分布式锁",
        "Lua",
        "Redisson",
        "缓存穿透",
        "缓存击穿",
        "缓存雪崩",
        "key",
        "过期时间",
    ],
    "agent": [
        "Agent",
        "RAG",
        "LangGraph",
        "LangChain",
        "Embedding",
        "Chroma",
        "向量数据库",
        "Prompt",
        "LLM",
    ],
}
TECH_KEYWORD_VARIANTS = {
    "Spring Boot": ["spring boot", "springboot"],
    "Spring Cloud": ["spring cloud", "springcloud"],
    "MyBatis": ["mybatis"],
    "RocketMQ": ["rocketmq"],
    "RabbitMQ": ["rabbitmq"],
    "Redisson": ["redisson"],
    "Embedding": ["embedding"],
    "Prompt": ["prompt"],
    "Chroma": ["chroma"],
    "Agent": ["agent"],
    "Redis": ["redis"],
    "MySQL": ["mysql"],
    "Java": ["java"],
    "JVM": ["jvm"],
    "Spring": ["spring"],
    "Kafka": ["kafka"],
    "Nacos": ["nacos"],
    "Sentinel": ["sentinel"],
    "Seata": ["seata"],
    "Docker": ["docker"],
    "Nginx": ["nginx"],
    "Linux": ["linux"],
    "RAG": ["rag"],
    "LLM": ["llm"],
    "Lua": ["lua"],
    "Python": ["python"],
    "LangChain": ["langchain"],
    "LangGraph": ["langgraph"],
    "FastAPI": ["fastapi"],
}


def _rag_log(message: str) -> None:
    print(message, flush=True)
    logger.info(message)


def extract_tech_keywords(text: str) -> list[str]:
    source_text = text or ""
    normalized_text = source_text.lower()
    keywords: list[str] = []
    seen: set[str] = set()

    for keyword in TECH_KEYWORDS:
        if keyword in seen:
            continue
        if keyword.isascii():
            variants = TECH_KEYWORD_VARIANTS.get(keyword, [keyword.lower()])
            for variant in variants:
                pattern = rf"(?<![a-z0-9+#]){re.escape(variant)}(?![a-z0-9+#])"
                if re.search(pattern, normalized_text):
                    keywords.append(keyword)
                    seen.add(keyword)
                    break
        elif keyword in source_text:
            keywords.append(keyword)
            seen.add(keyword)

    return keywords


def _content_for_item(item: dict[str, Any]) -> str:
    return str(item.get("clean_content") or item.get("content") or "").strip()


def _dedupe_key(item: dict[str, Any]) -> str:
    source = str(item.get("source") or "").strip()
    title = str(item.get("title") or "").strip()
    content = _content_for_item(item)
    return f"{source}::{title or content[:50]}"


def _normalize_text(text: str) -> str:
    return " ".join((text or "").lower().split())


def _contains_keyword(text: str, keyword: str) -> bool:
    normalized_text = _normalize_text(text)
    normalized_keyword = _normalize_text(keyword)
    if not normalized_keyword:
        return False
    if keyword.isascii():
        pattern = rf"(?<![a-z0-9+#]){re.escape(normalized_keyword)}(?![a-z0-9+#])"
        return re.search(pattern, normalized_text) is not None
    return normalized_keyword in normalized_text


def _match_keyword_count(text: str, keywords: list[str]) -> int:
    return sum(1 for keyword in keywords if _contains_keyword(text, keyword))


def _rank_knowledge_item(
    item: dict[str, Any],
    job_keywords: list[str],
    resume_keywords: list[str],
    has_ai_keywords: bool,
) -> float:
    score = item.get("score")
    distance = float(score) if score is not None else 999.0
    rank_score = -distance

    title = str(item.get("title") or "")
    source = str(item.get("source") or "").lower()
    content = _content_for_item(item)
    text_blob = f"{title}\n{content}"

    rank_score += _match_keyword_count(text_blob, job_keywords) * 2.0
    rank_score += _match_keyword_count(text_blob, resume_keywords) * 1.5

    source_bonus_keywords = {
        "java": "Java",
        "mysql": "MySQL",
        "redis": "Redis",
    }
    all_keywords = set(job_keywords) | set(resume_keywords)
    for source_key, keyword in source_bonus_keywords.items():
        if source_key in source and keyword in all_keywords:
            rank_score += 2.0

    if "agent" in source:
        rank_score += 2.0 if has_ai_keywords else -2.0

    if len(content) < 50:
        rank_score -= 3.0

    if any(generic in title for generic in GENERIC_TITLE_KEYWORDS):
        rank_score -= 2.0

    return rank_score


def _looks_like_ai_agent_job(job_jd: str) -> bool:
    normalized = _normalize_text(job_jd)
    return any(
        phrase in normalized
        for phrase in ("ai应用开发", "agent", "rag", "langgraph", "langchain")
    )


def _detect_required_categories(job_keywords: list[str], resume_keywords: list[str]) -> list[str]:
    all_keywords = set(job_keywords) | set(resume_keywords)
    required: list[str] = []

    mysql_signals = {"MySQL", "索引", "事务", "MVCC", "SQL", "InnoDB"}
    redis_signals = {"Redis", "缓存", "分布式锁", "Lua", "Redisson"}
    java_signals = {"Java", "JVM", "Spring Boot", "线程池", "多线程", "并发", "锁"}
    agent_signals = {"Agent", "RAG", "LangGraph", "LangChain", "Embedding", "Chroma", "LLM", "Prompt"}

    if all_keywords & mysql_signals:
        required.append("mysql")
    if all_keywords & redis_signals:
        required.append("redis")
    if all_keywords & java_signals:
        required.append("java")
    if all_keywords & agent_signals:
        required.append("agent")

    if not required:
        required = ["java", "mysql", "redis"]

    return required


def _detect_category(item: dict[str, Any]) -> str:
    source = str(item.get("source") or "").lower()
    title = str(item.get("title") or "")
    content = _content_for_item(item)
    text_blob = f"{title}\n{content}"

    if "redis" in source:
        return "redis"
    if "mysql" in source:
        return "mysql"
    if "java" in source:
        return "java"
    if "agent" in source:
        return "agent"

    if any(_contains_keyword(text_blob, keyword) for keyword in CATEGORY_KEYWORDS["redis"]):
        return "redis"
    if any(_contains_keyword(text_blob, keyword) for keyword in CATEGORY_KEYWORDS["mysql"]):
        return "mysql"
    if any(_contains_keyword(text_blob, keyword) for keyword in CATEGORY_KEYWORDS["java"]):
        return "java"
    if any(_contains_keyword(text_blob, keyword) for keyword in CATEGORY_KEYWORDS["agent"]):
        return "agent"
    return "other"


def _category_core_match(category: str, item: dict[str, Any]) -> bool:
    if category not in CATEGORY_KEYWORDS:
        return False
    title = str(item.get("title") or "")
    content = _content_for_item(item)
    text_blob = f"{title}\n{content}"
    return any(_contains_keyword(text_blob, keyword) for keyword in CATEGORY_KEYWORDS[category])


def _select_balanced_items(
    ranked_items: list[dict[str, Any]],
    required_categories: list[str],
    allow_agent_limit: int,
) -> list[dict[str, Any]]:
    category_groups: dict[str, list[dict[str, Any]]] = {
        "java": [],
        "mysql": [],
        "redis": [],
        "agent": [],
        "other": [],
    }
    for item in ranked_items:
        category_groups[item["category"]].append(item)

    selected: list[dict[str, Any]] = []
    selected_keys: set[str] = set()
    category_counts: dict[str, int] = {key: 0 for key in category_groups}

    for category in required_categories:
        candidates = category_groups.get(category, [])
        if category == "agent" and allow_agent_limit <= 0:
            continue
        for candidate in candidates:
            key = _dedupe_key(candidate)
            if key in selected_keys:
                continue
            if category == "agent" and category_counts["agent"] >= allow_agent_limit:
                break
            selected.append(candidate)
            selected_keys.add(key)
            category_counts[category] += 1
            _rag_log(
                f"[RAG] selected category={category} title={candidate.get('title') or '<empty>'} "
                f"source={candidate.get('source') or '<empty>'} rank_score={candidate.get('rank_score')}"
            )
            break
        if len(selected) >= 5:
            return selected[:5]

    for candidate in ranked_items:
        if len(selected) >= 5:
            break
        key = _dedupe_key(candidate)
        if key in selected_keys:
            continue
        if candidate["category"] == "agent" and category_counts["agent"] >= allow_agent_limit:
            continue
        if candidate["category"] == "agent" and "agent" not in required_categories and allow_agent_limit <= 0:
            continue
        selected.append(candidate)
        selected_keys.add(key)
        category_counts[candidate["category"]] += 1

    if len(selected) < 5 and allow_agent_limit <= 0:
        for candidate in ranked_items:
            if len(selected) >= 5:
                break
            if candidate["category"] != "agent":
                continue
            key = _dedupe_key(candidate)
            if key in selected_keys:
                continue
            selected.append(candidate)
            selected_keys.add(key)
            category_counts["agent"] += 1

    return selected[:5]


def load_resume_node(state: AgentAnalyzeState) -> dict[str, Any]:
    resume = get_resume_by_id(state["resume_id"])
    if resume is None:
        return {"error_msg": "Resume not found"}
    return {"resume": resume}


def load_job_node(state: AgentAnalyzeState) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}

    job = get_job_by_id(state["job_id"])
    if job is None:
        return {"error_msg": "Job not found"}
    return {"job": job}


def build_prompt_node(state: AgentAnalyzeState) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}

    prompt_template = read_prompt_template("match_analyze.txt")
    prompt = prompt_template.format(
        resume_content=state["resume"]["content"],
        job_jd=state["job"]["jd_text"],
    )
    return {"prompt": prompt}


def llm_analyze_node(state: AgentAnalyzeState) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}

    raw_output = invoke_llm(state["prompt"])
    return {"raw_output": raw_output}


def parse_result_node(state: AgentAnalyzeState) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}

    raw_output = state["raw_output"] or ""
    analysis = parse_llm_json_output(raw_output)
    return {"analysis": analysis}


def save_task_node(state: AgentAnalyzeState) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}

    task_id = save_success_task(
        task_type="MATCH_ANALYZE",
        resume_id=state["resume_id"],
        job_id=state["job_id"],
        output_data=state["analysis"],
    )
    return {"task_id": task_id}


def build_optimize_prompt_node(state: AgentAnalyzeState) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}

    prompt_template = read_prompt_template("resume_optimize.txt")
    prompt = prompt_template.format(
        resume_content=state["resume"]["content"],
        job_jd=state["job"]["jd_text"],
    )
    return {"prompt": prompt}


def llm_optimize_node(state: AgentAnalyzeState) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}

    raw_output = invoke_llm(state["prompt"])
    return {"raw_output": raw_output}


def parse_optimization_node(state: AgentAnalyzeState) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}

    raw_output = state["raw_output"] or ""
    optimization = parse_llm_json_output(raw_output)
    return {"optimization": optimization}


def save_optimize_task_node(state: AgentAnalyzeState) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}

    task_id = save_success_task(
        task_type="RESUME_OPTIMIZE",
        resume_id=state["resume_id"],
        job_id=state["job_id"],
        output_data=state["optimization"],
    )
    return {"task_id": task_id}


def retrieve_knowledge_node(state: AgentAnalyzeState) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}
    if state.get("enable_rag") is False:
        _rag_log("[RAG][interview] skipped: enable_rag=false")
        return {
            "knowledge_context": "",
            "knowledge_used": False,
            "knowledge_count": 0,
            "rag_queries": [],
            "rag_hit_titles": [],
            "rag_hit_sources": [],
        }

    resume = state.get("resume") or {}
    job = state.get("job") or {}
    resume_content = str(resume.get("content", ""))
    job_jd = str(job.get("jd_text", ""))

    _rag_log("[RAG][interview] retrieve_knowledge_node started")

    job_keywords = extract_tech_keywords(job_jd)
    resume_keywords = extract_tech_keywords(resume_content)
    all_keywords = list(dict.fromkeys(job_keywords + resume_keywords))
    backend_keywords = [keyword for keyword in all_keywords if keyword in BACKEND_KEYWORDS]
    has_ai_keywords = any(keyword in AI_KEYWORDS for keyword in all_keywords)
    required_categories = _detect_required_categories(job_keywords, resume_keywords)
    allow_agent_limit = 0
    if "agent" in required_categories:
        allow_agent_limit = 2 if _looks_like_ai_agent_job(job_jd) else 1

    job_query = f"岗位核心技术栈面试题：{' '.join(job_keywords)}" if job_keywords else ""
    resume_query = f"候选人项目技术栈面试追问：{' '.join(resume_keywords)}" if resume_keywords else ""
    backend_query = (
        f"Java 后端基础面试题：{' '.join(backend_keywords)}"
        if backend_keywords
        else "Java 后端 MySQL Redis Spring Boot JVM 并发 线程池 索引 缓存 分布式锁"
    )
    mysql_query = (
        "MySQL 面试题 索引 B+树 事务 MVCC InnoDB SQL 慢查询 主从复制 binlog redo log undo log"
        if "mysql" in required_categories
        else ""
    )
    ai_query = (
        "AI 应用 RAG Agent LangGraph Embedding 向量数据库 面试题"
        if has_ai_keywords
        else ""
    )

    _rag_log(f"[RAG] job_keywords={job_keywords}")
    _rag_log(f"[RAG] resume_keywords={resume_keywords}")
    _rag_log(f"[RAG] job_query={job_query or '<empty>'}")
    _rag_log(f"[RAG] resume_query={resume_query or '<empty>'}")
    _rag_log(f"[RAG] backend_query={backend_query}")
    _rag_log(f"[RAG] mysql_query={mysql_query or '<skipped>'}")
    _rag_log(f"[RAG] ai_query={ai_query or '<skipped>'}")
    _rag_log(f"[RAG] required_categories={required_categories}")

    query_plan: list[tuple[str, str, int]] = []
    if job_query:
        query_plan.append(("job", job_query, 3))
    if resume_query:
        query_plan.append(("resume", resume_query, 3))
    query_plan.append(("backend", backend_query, 4))
    if mysql_query:
        query_plan.append(("mysql", mysql_query, 3))
    if ai_query:
        query_plan.append(("ai", ai_query, 2))

    merged_items: list[dict[str, Any]] = []
    errors: list[str] = []

    for query_name, query_text, top_k in query_plan:
        try:
            items = search_knowledge(query=query_text, top_k=top_k)
            _rag_log(f"[RAG] {query_name}_hits={len(items)}")
            merged_items.extend(items)
        except Exception as exc:
            errors.append(f"{query_name}: {exc}")
            _rag_log(f"[RAG] fallback on {query_name}_query: {exc}")

    if not merged_items:
        if errors:
            _rag_log(f"[RAG] fallback: all retrieval failed: {' | '.join(errors)}")
        else:
            _rag_log("[RAG] fallback: no knowledge matched")
        return {
            "knowledge_context": "",
            "knowledge_used": False,
            "knowledge_count": 0,
            "rag_queries": [query for _, query, _ in query_plan],
            "rag_hit_titles": [],
            "rag_hit_sources": [],
        }

    deduped_items: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for item in merged_items:
        content = _content_for_item(item)
        category = _detect_category(item)
        short_content = len(content) < 50
        if short_content and not _category_core_match(category, item):
            continue
        key = _dedupe_key(item)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        item_copy = dict(item)
        item_copy["category"] = category
        if short_content:
            item_copy["short_content_penalty"] = 1
        deduped_items.append(item_copy)

    ranked_items: list[dict[str, Any]] = []
    for item in deduped_items:
        item_with_rank = dict(item)
        item_with_rank["rank_score"] = _rank_knowledge_item(
            item=item,
            job_keywords=job_keywords,
            resume_keywords=resume_keywords,
            has_ai_keywords=has_ai_keywords,
        )
        if item_with_rank.get("short_content_penalty"):
            item_with_rank["rank_score"] -= 3.0
        ranked_items.append(item_with_rank)

    ranked_items.sort(key=lambda item: item["rank_score"], reverse=True)
    for category in ("mysql", "redis", "java", "agent", "other"):
        candidates = [item for item in ranked_items if item.get("category") == category]
        _rag_log(f"[RAG] category={category} candidates={len(candidates)}")

    final_items = _select_balanced_items(
        ranked_items=ranked_items,
        required_categories=required_categories,
        allow_agent_limit=allow_agent_limit,
    )

    blocks: list[str] = []
    hit_titles: list[str] = []
    hit_sources: list[str] = []
    for index, item in enumerate(final_items, start=1):
        title = str(item.get("title") or "").strip()
        source = str(item.get("source") or "").strip()
        score = item.get("score")
        rank_score = item.get("rank_score")
        content = _content_for_item(item)
        if not content:
            continue

        _rag_log(
            "[RAG] hit "
            f"title={title or '<empty>'} source={source or '<empty>'} "
            f"score={score} rank_score={rank_score}"
        )

        blocks.append(
            "\n".join(
                [
                    f"【知识片段{index}】",
                    f"标题：{title}",
                    f"来源：{source}",
                    f"内容：{content}",
                ]
            )
        )
        hit_titles.append(title)
        hit_sources.append(source)

    knowledge_count = len(blocks)
    _rag_log(f"[RAG] final knowledge_count={knowledge_count}")

    if not blocks:
        _rag_log("[RAG] fallback: all merged items filtered out")
        return {
            "knowledge_context": "",
            "knowledge_used": False,
            "knowledge_count": 0,
            "rag_queries": [query for _, query, _ in query_plan],
            "rag_hit_titles": [],
            "rag_hit_sources": [],
        }

    return {
        "knowledge_context": "\n\n".join(blocks),
        "knowledge_used": True,
        "knowledge_count": knowledge_count,
        "rag_queries": [query for _, query, _ in query_plan],
        "rag_hit_titles": hit_titles,
        "rag_hit_sources": hit_sources,
    }


def build_interview_questions_prompt_node(state: AgentAnalyzeState) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}

    prompt_template = read_prompt_template("interview_questions.txt")
    prompt = prompt_template.format(
        resume_content=state["resume"]["content"],
        job_jd=state["job"]["jd_text"],
        knowledge_context=state.get("knowledge_context") or "",
    )
    return {"prompt": prompt}


def llm_generate_questions_node(state: AgentAnalyzeState) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}
    raw_output = invoke_llm(state["prompt"])
    return {"raw_output": raw_output}


def parse_questions_node(state: AgentAnalyzeState) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}
    raw_output = state["raw_output"] or ""
    interview_questions = parse_llm_json_output(raw_output)
    return {"interview_questions": interview_questions}


def save_questions_task_node(state: AgentAnalyzeState) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}

    task_id = save_success_task(
        task_type="INTERVIEW_QUESTIONS",
        resume_id=state["resume_id"],
        job_id=state["job_id"],
        output_data=state["interview_questions"],
        input_data={
            "resume_id": state["resume_id"],
            "job_id": state["job_id"],
            "enable_rag": bool(state.get("enable_rag", True)),
            "knowledge_used": bool(state.get("knowledge_used")),
            "knowledge_count": state.get("knowledge_count") or 0,
            "rag_queries": state.get("rag_queries") or [],
            "rag_hit_titles": state.get("rag_hit_titles") or [],
            "rag_hit_sources": state.get("rag_hit_sources") or [],
        },
    )
    return {"task_id": task_id}


def _route_on_error(state: AgentAnalyzeState) -> str:
    if state.get("error_msg"):
        return END
    return "load_job"


def _route_after_job(state: AgentAnalyzeState) -> str:
    if state.get("error_msg"):
        return END
    return "build_prompt"


def _route_after_job_for_optimize(state: AgentAnalyzeState) -> str:
    if state.get("error_msg"):
        return END
    return "build_optimize_prompt"


def _route_after_job_for_interview(state: AgentAnalyzeState) -> str:
    if state.get("error_msg"):
        return END
    return "retrieve_knowledge"


workflow = StateGraph(AgentAnalyzeState)
workflow.add_node("load_resume", load_resume_node)
workflow.add_node("load_job", load_job_node)
workflow.add_node("build_prompt", build_prompt_node)
workflow.add_node("llm_analyze", llm_analyze_node)
workflow.add_node("parse_result", parse_result_node)
workflow.add_node("save_task", save_task_node)
workflow.add_edge(START, "load_resume")
workflow.add_conditional_edges("load_resume", _route_on_error, ["load_job", END])
workflow.add_conditional_edges("load_job", _route_after_job, ["build_prompt", END])
workflow.add_edge("build_prompt", "llm_analyze")
workflow.add_edge("llm_analyze", "parse_result")
workflow.add_edge("parse_result", "save_task")
workflow.add_edge("save_task", END)

analyze_graph = workflow.compile()

optimize_workflow = StateGraph(AgentAnalyzeState)
optimize_workflow.add_node("load_resume", load_resume_node)
optimize_workflow.add_node("load_job", load_job_node)
optimize_workflow.add_node("build_optimize_prompt", build_optimize_prompt_node)
optimize_workflow.add_node("llm_optimize", llm_optimize_node)
optimize_workflow.add_node("parse_optimization", parse_optimization_node)
optimize_workflow.add_node("save_optimize_task", save_optimize_task_node)
optimize_workflow.add_edge(START, "load_resume")
optimize_workflow.add_conditional_edges("load_resume", _route_on_error, ["load_job", END])
optimize_workflow.add_conditional_edges("load_job", _route_after_job_for_optimize, ["build_optimize_prompt", END])
optimize_workflow.add_edge("build_optimize_prompt", "llm_optimize")
optimize_workflow.add_edge("llm_optimize", "parse_optimization")
optimize_workflow.add_edge("parse_optimization", "save_optimize_task")
optimize_workflow.add_edge("save_optimize_task", END)

optimize_resume_graph = optimize_workflow.compile()

interview_workflow = StateGraph(AgentAnalyzeState)
interview_workflow.add_node("load_resume", load_resume_node)
interview_workflow.add_node("load_job", load_job_node)
interview_workflow.add_node("retrieve_knowledge", retrieve_knowledge_node)
interview_workflow.add_node("build_interview_questions_prompt", build_interview_questions_prompt_node)
interview_workflow.add_node("llm_interview", llm_generate_questions_node)
interview_workflow.add_node("parse_questions", parse_questions_node)
interview_workflow.add_node("save_questions_task", save_questions_task_node)
interview_workflow.add_edge(START, "load_resume")
interview_workflow.add_conditional_edges("load_resume", _route_on_error, ["load_job", END])
interview_workflow.add_conditional_edges("load_job", _route_after_job_for_interview, ["retrieve_knowledge", END])
interview_workflow.add_edge("retrieve_knowledge", "build_interview_questions_prompt")
interview_workflow.add_edge("build_interview_questions_prompt", "llm_interview")
interview_workflow.add_edge("llm_interview", "parse_questions")
interview_workflow.add_edge("parse_questions", "save_questions_task")
interview_workflow.add_edge("save_questions_task", END)

interview_graph = interview_workflow.compile()


def run_analyze_workflow(resume_id: int, job_id: int) -> dict[str, Any]:
    initial_state: AgentAnalyzeState = {
        "resume_id": resume_id,
        "job_id": job_id,
        "enable_rag": None,
        "resume": None,
        "job": None,
        "knowledge_context": None,
        "knowledge_used": None,
        "knowledge_count": None,
        "rag_queries": None,
        "rag_hit_titles": None,
        "rag_hit_sources": None,
        "prompt": None,
        "raw_output": None,
        "analysis": None,
        "optimization": None,
        "interview_questions": None,
        "task_id": None,
        "error_msg": None,
    }
    final_state = analyze_graph.invoke(initial_state)
    return {
        "task_id": final_state.get("task_id"),
        "analysis": final_state.get("analysis"),
        "error_msg": final_state.get("error_msg"),
    }


def run_optimize_resume_workflow(resume_id: int, job_id: int) -> dict[str, Any]:
    initial_state: AgentAnalyzeState = {
        "resume_id": resume_id,
        "job_id": job_id,
        "enable_rag": None,
        "resume": None,
        "job": None,
        "knowledge_context": None,
        "knowledge_used": None,
        "knowledge_count": None,
        "rag_queries": None,
        "rag_hit_titles": None,
        "rag_hit_sources": None,
        "prompt": None,
        "raw_output": None,
        "analysis": None,
        "optimization": None,
        "interview_questions": None,
        "task_id": None,
        "error_msg": None,
    }
    final_state = optimize_resume_graph.invoke(initial_state)
    return {
        "task_id": final_state.get("task_id"),
        "optimization": final_state.get("optimization"),
        "error_msg": final_state.get("error_msg"),
    }


def run_interview_questions_workflow(resume_id: int, job_id: int, enable_rag: bool = True) -> dict[str, Any]:
    initial_state: AgentAnalyzeState = {
        "resume_id": resume_id,
        "job_id": job_id,
        "enable_rag": enable_rag,
        "resume": None,
        "job": None,
        "knowledge_context": None,
        "knowledge_used": None,
        "knowledge_count": None,
        "rag_queries": None,
        "rag_hit_titles": None,
        "rag_hit_sources": None,
        "prompt": None,
        "raw_output": None,
        "analysis": None,
        "optimization": None,
        "interview_questions": None,
        "task_id": None,
        "error_msg": None,
    }
    final_state = interview_graph.invoke(initial_state)
    return {
        "task_id": final_state.get("task_id"),
        "interview_questions": final_state.get("interview_questions"),
        "error_msg": final_state.get("error_msg"),
    }
