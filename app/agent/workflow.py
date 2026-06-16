import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agent.common import analyze_resume_job, get_prompt_manager, parse_llm_json_output, save_success_task
from app.agent.state import AgentAnalyzeState, make_initial_state
from app.core.llm import invoke_llm
from app.db.crud import get_job_by_id, get_resume_by_id
from app.rag.rag_service import search_knowledge

logger = logging.getLogger(__name__)

# ── 通用技术术语提取（语言无关，不依赖硬编码词表） ──

# 英文技术术语：CamelCase（React, SpringBoot）或全大写缩写（JVM, API）
_TECH_TERM_RE = re.compile(r"\b([A-Z][a-zA-Z0-9+#.]{1,36})\b")
# 中文引号、尖括号、方括号包裹的技术名词
_CN_BRACKET_RE = re.compile(r"[《「【]([^》」】]+)[》」】]")

# 常见英文非技术词，避免误提取
_SKIP_WORDS: set[str] = {
    "The", "A", "An", "I", "We", "You", "He", "She", "It", "They",
    "This", "That", "These", "Those", "Here", "There",
    "Is", "Are", "Was", "Were", "Be", "Been", "Being",
    "Can", "Will", "Would", "Could", "Should", "May", "Might", "Must",
    "Has", "Have", "Had", "Do", "Does", "Did",
    "In", "On", "At", "To", "For", "Of", "With", "By", "From",
    "And", "Or", "But", "Not", "No", "Yes", "If", "So",
    "All", "Each", "Any", "Some", "More", "Most",
    "One", "Two", "First", "Next", "Other",
    "About", "Also", "Just", "Only", "Very", "How", "What", "When",
    "Then", "Now", "Still", "Even", "Such", "Than", "Like",
}

# 用于从文本中提取短命题（中文场景：顿号/逗号分隔的技术短语）
_CN_PHRASE_RE = re.compile(r"[一-鿿、。，《》！？；：“”‘’—…]{2,}")


def _rag_log(message: str) -> None:
    print(message, flush=True)
    logger.info(message)


def _extract_tech_terms(text: str) -> list[str]:
    """从文本中提取技术术语（语言无关，正则匹配，不依赖硬编码词表）。

    提取规则：
    1. 英文 CamelCase / 全大写缩写词，过滤常见非技术词
    2. 中文书名号/方括号包裹的专有名词
    """
    source = text or ""
    terms: list[str] = []
    seen: set[str] = {"API", "SDK", "JDK", "JVM"}  # 少数几个极常见的不算

    # 英文技术术语
    for match in _TECH_TERM_RE.finditer(source):
        word = match.group(1)
        if word in _SKIP_WORDS or word.lower() in _SKIP_WORDS:
            continue
        if word in seen:
            continue
        seen.add(word)
        terms.append(word)

    # 中文书名号/方括号里的专有名词（如《深入理解 JVM》）
    for match in _CN_BRACKET_RE.finditer(source):
        phrase = match.group(1).strip()
        if len(phrase) >= 2 and phrase not in seen:
            seen.add(phrase)
            terms.append(phrase)

    return terms


def _get_kb_source_names(knowledge_dir: str = "") -> list[str]:
    """从知识库文件名自动推断知识来源类别（文件名即类别）。"""
    base = Path(knowledge_dir) if knowledge_dir else Path("data/knowledge")
    if not base.exists() or not base.is_dir():
        return []
    names: list[str] = []
    for fpath in sorted(base.rglob("*.md")):
        names.append(fpath.stem)
    for fpath in sorted(base.rglob("*.txt")):
        names.append(fpath.stem)
    return names


def _dedupe_key(item: dict[str, Any]) -> str:
    """去重键：来源 + 标题（或内容前 50 字）。"""
    source = str(item.get("source") or "").strip()
    title = str(item.get("title") or "").strip()
    content = str(item.get("content") or "").strip()
    return f"{source}::{title or content[:50]}"


def retrieve_knowledge_node(state: AgentAnalyzeState) -> dict[str, Any]:
    """RAG 知识检索节点（通用版）。

    流程：
    1. 用正则从简历+JD 中提取技术术语（任何技术栈通用）
    2. 按"术语"和"知识库来源×术语"两维度构造查询
    3. 向量搜索 → 去重 → 按相似度排序 → 来源多样性选取 TOP 5
    """
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

    # ── 1. 动态提取技术术语（语言无关） ──
    job_terms = _extract_tech_terms(job_jd)
    resume_terms = _extract_tech_terms(resume_content)
    all_terms = list(dict.fromkeys(job_terms + resume_terms))  # 保序去重
    kb_sources = _get_kb_source_names()

    _rag_log(f"[RAG] job_terms={job_terms}")
    _rag_log(f"[RAG] resume_terms={resume_terms}")
    _rag_log(f"[RAG] kb_sources={kb_sources}")

    # ── 2. 动态构造查询计划 ──
    query_plan: list[tuple[str, str, int]] = []

    # 维度A：纯术语作为查询
    for term in all_terms:
        query_plan.append((f"term:{term}", f"{term} 面试题", 2))

    # 维度B：知识库来源 × 前几个术语组合查询
    top_terms = all_terms[:4]
    for source in kb_sources:
        prefix = f"{source} 面试"
        if top_terms:
            combined = f"{prefix} {' '.join(top_terms)}"
        else:
            combined = f"{prefix} 核心知识点"
        query_plan.append((f"source×term:{source}", combined, 3))

    # 兜底：如果术语和知识库都太少
    if not query_plan:
        query_plan.append(("fallback", "面试题 核心技术 原理", 5))

    _rag_log(f"[RAG] query_plan count={len(query_plan)}")

    # ── 3. 并发执行查询（线程池），合并结果 ──
    merged_items: list[dict[str, Any]] = []
    errors: list[str] = []

    if query_plan:
        with ThreadPoolExecutor(max_workers=min(len(query_plan), 8)) as pool:
            future_to_name: dict = {}
            for name, query_text, top_k in query_plan:
                future = pool.submit(search_knowledge, query_text, top_k)
                future_to_name[future] = name

            for future in as_completed(future_to_name):
                name = future_to_name[future]
                try:
                    items = future.result()
                    _rag_log(f"[RAG] {name}_hits={len(items)}")
                    merged_items.extend(items)
                except Exception as exc:
                    errors.append(f"{name}: {exc}")
                    _rag_log(f"[RAG] query failed {name}: {exc}")

    if not merged_items:
        _rag_log(f"[RAG] no results: errors={'|'.join(errors)}" if errors else "[RAG] no results")
        return {
            "knowledge_context": "",
            "knowledge_used": False,
            "knowledge_count": 0,
            "rag_queries": [q for _, q, _ in query_plan],
            "rag_hit_titles": [],
            "rag_hit_sources": [],
        }

    # ── 4. 去重 + 过滤过短内容 + 按向量分数排序 ──
    deduped: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for item in merged_items:
        content = str(item.get("content") or "").strip()
        if len(content) < 40:
            continue
        key = _dedupe_key(item)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(dict(item))

    deduped.sort(key=lambda x: x.get("score") if x.get("score") is not None else 999.0)

    # ── 5. 来源多样性选取 TOP 5 ──
    final_items: list[dict[str, Any]] = []
    source_counts: dict[str, int] = {}
    MAX_PER_SOURCE = 2

    for item in deduped:
        if len(final_items) >= 5:
            break
        source = str(item.get("source") or "")
        if source_counts.get(source, 0) >= MAX_PER_SOURCE:
            continue
        final_items.append(item)
        source_counts[source] = source_counts.get(source, 0) + 1

    # ── 6. 格式化输出 ──
    blocks: list[str] = []
    hit_titles: list[str] = []
    hit_sources: list[str] = []

    for index, item in enumerate(final_items, start=1):
        title = str(item.get("title") or "").strip()
        source = str(item.get("source") or "").strip()
        content = str(item.get("content") or "").strip()
        if not content:
            continue

        _rag_log(
            f"[RAG] hit title={title or '<empty>'} "
            f"source={source or '<empty>'} score={item.get('score')}"
        )

        blocks.append(
            "\n".join([
                f"【知识片段{index}】",
                f"标题：{title}",
                f"来源：{source}",
                f"内容：{content}",
            ])
        )
        hit_titles.append(title)
        hit_sources.append(source)

    knowledge_count = len(blocks)
    _rag_log(f"[RAG] final knowledge_count={knowledge_count}")

    if not blocks:
        _rag_log("[RAG] fallback: all items filtered out")
        return {
            "knowledge_context": "",
            "knowledge_used": False,
            "knowledge_count": 0,
            "rag_queries": [q for _, q, _ in query_plan],
            "rag_hit_titles": [],
            "rag_hit_sources": [],
        }

    return {
        "knowledge_context": "\n\n".join(blocks),
        "knowledge_used": True,
        "knowledge_count": knowledge_count,
        "rag_queries": [q for _, q, _ in query_plan],
        "rag_hit_titles": hit_titles,
        "rag_hit_sources": hit_sources,
    }


def load_resume_node(state: AgentAnalyzeState) -> dict[str, Any]:
    resume = get_resume_by_id(state["resume_id"], user_id=state["user_id"])
    if resume is None:
        return {"error_msg": "Resume not found"}
    return {"resume": resume}


def load_job_node(state: AgentAnalyzeState) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}

    job = get_job_by_id(state["job_id"], user_id=state["user_id"])
    if job is None:
        return {"error_msg": "Job not found"}
    return {"job": job}


def build_prompt_node(state: AgentAnalyzeState) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}

    prompt = get_prompt_manager().render(
        "match_analyze",
        resume_content=state["resume"]["content"],
        job_jd=state["job"]["jd_text"],
    )
    return {"prompt": prompt}


def llm_analyze_node(state: AgentAnalyzeState) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}

    analysis = analyze_resume_job(
        resume_content=state["resume"]["content"],
        job_jd=state["job"]["jd_text"],
    )
    return {"analysis": analysis}


def parse_result_node(state: AgentAnalyzeState) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}

    return {"analysis": state.get("analysis") or {}}


def save_task_node(state: AgentAnalyzeState) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}

    task_id = save_success_task(
        task_type="MATCH_ANALYZE",
        resume_id=state["resume_id"],
        job_id=state["job_id"],
        output_data=state["analysis"],
        input_data={
            "resume_id": state["resume_id"],
            "job_id": state["job_id"],
            "local_resume_id": (state.get("resume") or {}).get("local_resume_id"),
            "local_job_id": (state.get("job") or {}).get("local_job_id"),
        },
        user_id=state["user_id"],
    )
    return {"task_id": task_id}


def build_optimize_prompt_node(state: AgentAnalyzeState) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}

    prompt = get_prompt_manager().render(
        "resume_optimize",
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
        input_data={
            "resume_id": state["resume_id"],
            "job_id": state["job_id"],
            "local_resume_id": (state.get("resume") or {}).get("local_resume_id"),
            "local_job_id": (state.get("job") or {}).get("local_job_id"),
        },
        user_id=state["user_id"],
    )
    return {"task_id": task_id}


def build_interview_questions_prompt_node(state: AgentAnalyzeState) -> dict[str, Any]:
    if state.get("error_msg"):
        return {}

    prompt = get_prompt_manager().render(
        "interview_questions",
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
            "local_resume_id": (state.get("resume") or {}).get("local_resume_id"),
            "local_job_id": (state.get("job") or {}).get("local_job_id"),
            "enable_rag": bool(state.get("enable_rag", True)),
            "knowledge_used": bool(state.get("knowledge_used")),
            "knowledge_count": state.get("knowledge_count") or 0,
            "rag_queries": state.get("rag_queries") or [],
            "rag_hit_titles": state.get("rag_hit_titles") or [],
            "rag_hit_sources": state.get("rag_hit_sources") or [],
        },
        user_id=state["user_id"],
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


def run_analyze_workflow(resume_id: int, job_id: int, user_id: int) -> dict[str, Any]:
    initial_state = make_initial_state(user_id, resume_id, job_id)
    final_state = analyze_graph.invoke(initial_state)
    return {
        "task_id": final_state.get("task_id"),
        "analysis": final_state.get("analysis"),
        "error_msg": final_state.get("error_msg"),
    }


def run_optimize_resume_workflow(resume_id: int, job_id: int, user_id: int) -> dict[str, Any]:
    initial_state = make_initial_state(user_id, resume_id, job_id)
    final_state = optimize_resume_graph.invoke(initial_state)
    return {
        "task_id": final_state.get("task_id"),
        "optimization": final_state.get("optimization"),
        "error_msg": final_state.get("error_msg"),
    }


def run_interview_questions_workflow(
    resume_id: int,
    job_id: int,
    user_id: int,
    enable_rag: bool = True,
) -> dict[str, Any]:
    initial_state = make_initial_state(user_id, resume_id, job_id, enable_rag=enable_rag)
    final_state = interview_graph.invoke(initial_state)
    return {
        "task_id": final_state.get("task_id"),
        "interview_questions": final_state.get("interview_questions"),
        "error_msg": final_state.get("error_msg"),
    }
