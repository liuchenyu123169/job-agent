# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 启动命令

```bash
# 后端 (http://127.0.0.1:8000)
pip install -r requirements.txt
cp .env.example .env   # 编辑填入 ZHIPU_API_KEY
python -m uvicorn app.main:app --reload --port 8000

# 前端 (http://127.0.0.1:5173)
cd frontend
npm install
npm run dev            # 开发服务器（热更新）
npm run build          # 生产构建到 dist/
```

## 技术栈

- **后端**: FastAPI + LangGraph + LangChain + SQLite + ChromaDB + JWT (python-jose)
- **前端**: Vue 3 (单页 SPA, Vite 构建, `frontend/src/`)
- **LLM**: 智谱 GLM (`glm-4-flash`) 通过 LangChain `ChatOpenAI` 兼容接口
- **Embedding**: 智谱 Embedding API, 存入 ChromaDB 向量库

## 架构分层

```
前端 ChatPanel (Vue SSE 流)
    ↓ POST /api/copilot/run
Copilot API — 两种模式:
  - 直通模式 (有 resume_id+job_id): 跳过 LLM Planner, 按 tools[] 列表顺序执行
  - ReAct 模式 (缺 ID): LangGraph agent 自主决策工具调用链
    ↓
Tool Registry (全局单例) → 8 个注册工具
    ↓
Agent Workflow (LangGraph StateGraph) — 每条 workflow 编译为独立 graph
    ↓
LLM / RAG / DB — 底层能力
```

## 关键文件（按阅读顺序）

| 文件 | 角色 |
|------|------|
| `app/main.py` | FastAPI app, CORS, 注册 7 个路由, startup 事件 |
| `app/core/config.py` | 环境变量: ZHIPU_BASE_URL, MODEL_NAME, JWT_SECRET_KEY |
| `app/core/llm.py` | `invoke_llm(prompt)` 纯文本 / `invoke_llm_with_tools(messages, tools)` 带 function calling |
| `app/tools/base.py` | `ToolDefinition` (name, description, parameters, execute, keywords, render_type) + `ToolResult` dataclass |
| `app/tools/registry.py` | `ToolRegistry` 全局单例, `tool_registry.list_all()` / `get_function_definitions()` |
| `app/tools/__init__.py` | 所有工具 import 触发注册, 新增工具在这里加一行 |
| `app/agent/workflow.py` | 3 个 LangGraph StateGraph: 匹配分析/简历优化/面试题生成, 每个编译为独立 graph + `run_*_workflow()` 入口 |
| `app/agent/common.py` | 共享: `read_prompt_template()`, `save_success_task()`, `normalize_match_score()`, `ensure_string_list()` |
| `app/agent/state.py` | `AgentAnalyzeState(TypedDict)` — 20 字段, 三个 workflow 共用 |
| `app/agent/recommend.py` | `recommend_jobs_for_resume()` — 逐岗位 LLM 打分排序 |
| `app/copilot/graph.py` | ReAct agent 循环: agent_node → router → tools_node → 回 agent_node |
| `app/copilot/state.py` | `PipelineContext` (累积工具结果) + `PipelineState` |
| `app/copilot/system_prompt.py` | `build_system_prompt()` 从 tool_registry 动态生成系统提示词 |
| `app/copilot/summarizer.py` | `summarize_result()` — 单次遍历生成结构化报告 + 文本摘要 |
| `app/api/copilot_api.py` | `POST /api/copilot/run` (SSE 流) + `GET /api/copilot/tools` (工具发现) + sessions CRUD |
| `app/api/agent_api.py` | 独立 REST 端点: `/analyze`, `/optimize-resume`, `/generate-interview-questions`, `/recommend-jobs` |
| `app/db/database.py` | SQLite 初始化 (5 表: user, resume, job, agent_task, copilot_session) |
| `app/rag/` | RAG 链路: loader → cleaner → splitter → embedding → vector_store (ChromaDB) |
| `app/prompts/` | LLM 提示词模板 (.txt): `match_analyze.txt`, `resume_optimize.txt`, `interview_questions.txt` |
| `frontend/src/App.vue` | 根组件 (~250 行): 侧边栏 + 面板路由 + provide 全局状态, CSS 全局样式 |
| `frontend/src/components/` | 7 个 SFC: AuthForm, ChatPanel, ResumePanel, JobPanel, RecommendPanel, TaskPanel, KnowledgePanel |
| `frontend/src/api.js` | Axios 客户端 + SSE 流解析 + 所有 API 方法 |

## 新增工具的标准流程

1. 写 prompt 模板 → `app/prompts/xxx.txt`
2. 写 workflow → `app/agent/workflow.py` 新增 StateGraph + `run_xxx_workflow()`
3. 写 tool 封装 → `app/tools/xxx_tool.py` (定义 ToolDefinition, 含 keywords + render_type)
4. 注册 → `app/tools/__init__.py` 加 `import app.tools.xxx_tool`
5. (可选) 独立 REST 端点 → `app/api/agent_api.py`
6. 前端渲染 → 若 render_type 已存在则自动渲染; 新类型需在 ChatPanel 加一个 `v-if` 块

注册后, system prompt、`/api/copilot/tools`、LLM function definitions 全部自动感知新工具。`render_type` 决定前端如何展示:
- `match_analysis` — 分数 + 优势/劣势/建议列表
- `questions` — 四类面试题分组
- `scored_list` — 按分数排序的卡片列表
- `item_list` — 通用条目列表
- `full_text` — 大段文本
- `generic` — 纯 JSON dump

## 重要约定

- 前端组件之间用 Vue `provide`/`inject` 共享状态 (App.vue provide, 子组件 inject)
- 所有 tool 的 execute 函数必须 `async`, 返回 `ToolResult`
- 所有 workflow 使用统一 `AgentAnalyzeState` TypedDict, 初始状态包含 20 个字段全部赋 None
- 任务结果通过 `save_success_task()` 持久化到 `agent_task` 表
- Copilot 对话上下文通过 `copilot_session` 表持久化 (JSON 列)
- 前端 SSE 解析在 `api.js` 的 `streamCopilot()` (POST + fetch + ReadableStream, 非 EventSource)
