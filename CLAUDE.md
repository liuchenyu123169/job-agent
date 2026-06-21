# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 启动

```bash
# 后端 (http://127.0.0.1:8000)
cp .env.example .env   # 填入 ZHIPU_API_KEY
pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000

# 前端 (http://127.0.0.1:5173)
cd frontend && npm install && npm run dev
```

## 技术栈

- **后端**: FastAPI + LangGraph + LangChain + SQLite + ChromaDB + JWT + Jinja2 + PyYAML + httpx
- **前端**: Vue 3 (SPA, Vite, `frontend/src/components/` 8个SFC)
- **LLM**: 智谱 GLM (`glm-4-flash`) 通过 LangChain `ChatOpenAI`

## 架构分层（从上到下）

```
用户输入
  ↓ ChatPanel.send() → POST /api/copilot/run {goal, session_id, resume_id, job_id}
  ↓
Copilot API — 后端 Skill 匹配自动选择路径:
  Skill命中 → _direct_agents 或 _direct_tools (零LLM路由)
  Skill未命中 → Coordinator ReAct 推理委派
  ↓
多轮对话: 带 session_id → 从 conversation_messages 表加载历史 → 注入 PipelineState
  ↓
Skill 系统 (app/skills/) → YAML配置, 关键词匹配用户意图, 决定mode+sub_agents/tools
  ↓
Coordinator (ReAct) → 委派子Agent(也是ToolDefinition) — 仅 fallback
  ↓ 子Agent内部是 LangGraph pipeline (复用 workflow.py 节点)
  ↓
LLM调用前: PromptManager.render() → Jinja2模板 + FewShot注入
  ↓
LLM / RAG / DB
```

**架构哲学**: Workflow 为主，Agent 为 fallback。能提前确定步骤的用 DAG 图，模糊意图才走 Coordinator。

## 关键模块

| 模块 | 路径 | 作用 |
|------|------|------|
| Prompt引擎 | `app/prompt_engine/` | PromptManager(Jinja2加载/渲染/版本切换) + FewShotStore(YAML示例库) + PromptEvaluator(AB对比) |
| 多Agent | `app/agents/` | Coordinator(ReAct调度者) + ResumeAgent + InterviewAgent + SearchAgent |
| Skill系统 | `app/skills/` | SkillRegistry(YAML加载/关键词匹配) + 6个skill配置 |
| 工具层 | `app/tools/` | ToolDefinition + ToolRegistry全局单例, 10个工具 |
| Workflow | `app/agent/workflow.py` | 5个LangGraph StateGraph + run_*_workflow() |
| Copilot | `app/copilot/` | ReAct graph + PipelineContext + ConversationManager + summarizer + system_prompt |
| 对话记忆 | `app/copilot/conversation.py` | ConversationManager(消息持久化/加载/去重/上下文窗口管理) |
| RAG | `app/rag/` | loader→cleaner→splitter→embedding→ChromaDB |
| 数据库 | `app/db/` | SQLite 6表: user/resume/job/agent_task/copilot_session/conversation_messages |

## 已实现的 Workflow（5个）

| Workflow | 图名 | 触发 Skill |
|----------|------|-----------|
| 匹配分析 | `analyze_graph` | match_analyze.yaml |
| 简历优化 | `optimize_resume_graph` | full_prep.yaml (→resume_agent) |
| 面试题生成 | `interview_graph` | interview_prep.yaml |
| 定制简历生成 | `generate_resume_graph` | custom_resume.yaml |
| 岗位推荐 | (recommend_jobs_tool) | find_jobs.yaml |

## 对话记忆系统

- `copilot_session` 存会话元信息（goal, status, context_json）
- `conversation_messages` 存每条消息（role, content, tool_calls_json）+ content_hash 去重
- 前端 localStorage 存 currentSessionId，刷新恢复历史
- 上下文窗口：token 估算超 6000 时规则摘要压缩旧消息
- 侧边栏"对话"下方显示历史会话列表

## 新增功能的标准流程

1. 写 Jinja2 模板 → `app/prompts/v1/xxx.j2`
2. (可选) 写 few-shot → `app/prompts/few_shots/xxx.yaml`
3. 写 workflow → `app/agent/workflow.py` 加 StateGraph + run函数
4. 写 tool → `app/tools/xxx_tool.py` (ToolDefinition + keywords + render_type)
5. 注册 → `app/tools/__init__.py` 加 import
6. 如需Skill编排 → `app/skills/xxx.yaml`

注册后 system_prompt、`/api/copilot/tools`、`/api/copilot/skills` 全部自动感知。

## 重要约定

- 架构以 Workflow 为主，Agent（Coordinator ReAct）仅做 fallback
- 前端组件用 Vue `provide`/`inject` 共享状态
- 所有 Tool.execute 必须 async, 返回 ToolResult
- 所有 workflow 共用 `AgentAnalyzeState` TypedDict (22字段)
- 子Agent从Coordinator视角看就是ToolDefinition (`_wrap_sub_agent_tool()`)
- 模板用 Jinja2 `{{ var }}` 语法, 不再用 `.format()`
- 前端SSE解析在 api.js `streamCopilot()` (POST+fetch+ReadableStream)
- 会话管理状态由 App.vue 持有，ChatPanel 通过 inject 消费

## Token 级 SSE 流式输出

### 数据流（从上到下）

```
用户输入 → _direct_agents() → agent.run_stream_async()
  → self._graph_async.astream(initial) → 异步 LLM 节点
  → _stream_llm_with_callback(prompt)
      ├── _token_callback(token) → on_token() → token_q → step_token_event() → SSE
      └── return "".join(buffer) → state["raw_output"] → parse → step_complete_event()
  → 前端 streamCopilot() → onStepToken → _streamText += token → renderMarkdown()
```

### 关键 ContextVar

| ContextVar | 回调签名 | 触发者 | 作用 |
|------------|---------|--------|------|
| `_step_callback` | `(node_name, duration_ms)` | `_trace_node` 包装器 | SSE step_progress |
| `_token_callback` | `(token_text)` | `_stream_llm_with_callback` | SSE step_token |

### 异步图 vs 同步图

- `build_pipeline()` → `self._graph` → 同步 `.invoke()` → 旧 API（`/api/agent/*`）用
- `build_pipeline_async()` → `self._graph_async` → 异步 `.astream()` → SSE 流式用
- LLM 节点成对存在：`llm_analyze_node`（sync, `invoke_llm`）/ `llm_analyze_node_async`（async, `_stream_llm_with_callback`）
- 异步图中 LLM 节点不加 `_trace_node` 包裹，token 回调独立推送
- `SearchAgent` 无 LLM 调用，`build_pipeline_async()` 直接返回 `self._graph`

### SSE 事件类型

| 事件 | 数据字段 | 触发时机 | 前端回调 |
|------|---------|---------|---------|
| `step_start` | `{tool, args}` | Agent/工具开始执行 | `onStepStart` |
| `step_progress` | `{agent, node, duration_ms, state_summary}` | 每个 workflow 节点完成 | `onStepProgress` |
| `step_token` | `{agent, token}` | LLM 逐 token 生成（批量合并后发送） | `onStepToken` |
| `step_complete` | `{tool, result}` | Agent/工具执行完毕 | `onStepComplete` |
| `error` | `{tool, error}` | 执行出错 | `onStepError` |
| `final` | `{summary, task_ids, session_id}` | 全部完成 | `onFinal` |

### Prompt 模板约定

- 所有模板要求 LLM 输出 **Markdown 笔记格式**，禁止 JSON
- 模板开头强制 `# 模块名` 作为一级标题（`#` → h2 渲染）
- 结构元素：`**加粗标题**：` + 内容、`- 列表`、`1. 有序列表`、`## 二级标题`
- 前端 `renderMarkdown()` 负责：`**bold**` → `<strong>`、`#` → `<h2>`、`-` → `<ul>`、`` `code` `` → `<code>`
- resume_generate.j2 仍输出纯 Markdown 简历正文，不在此规则内
- LLM 输出的文本字段（`analysis_text` 等）原样存储，不再调 `parse_llm_json_output` 解析

### 前端关键约定

- **`copilotMsg` 必须用 `reactive()` 包裹**：回调闭包捕获的是原始对象引用，直接修改不触发 Vue Proxy → UI 不更新
- **SSE 跨 chunk 状态保持**：`currentEvent` 作为闭包变量在 `_parseSSELines` 调用间传递，避免 TCP 分片导致事件名和数据行分离
- **`RequestIdMiddleware` 不继承 `BaseHTTPMiddleware`**：后者会读取整个响应体，破坏 `StreamingResponse`。已改为纯 ASGI middleware
- **流式文本用 `v-html` + `renderMarkdown()` 渲染**，不用 `{{ }}`（后者转义 HTML）
- **流式完成后光标消失**：`stream-text` div 在 `step.status === 'done'` 时移除 `cursor-blink` span

## 性能优化策略（按收益排序）

1. **减少 LLM 调用次数** — 合并输入相同的调用（如 match_analyze + optimize_resume），用模板拼 final summary
2. **缩小上下文窗口** — 简历/JD 先摘要再传入 Prompt，RAG 只放最相关的 2-4 条，会话历史只保留 summary
3. **轻任务用小模型** — 意图分类、关键词提取、格式化用 fast 模型，核心生成才用 primary 模型
4. **并行化独立任务** — 互不依赖的 Agent 可并行执行（当前仍串行）
5. **缓存高频结果** — 同一简历+岗位的匹配分析、面试题、RAG 检索结果，按 `hash(resume_id + job_id + task_type + prompt_version)` 缓存

## 待实现功能

1. **AI模拟面试** — 多轮对话：出题→用户回答→评估打分→追问→最终报告。新增 `mock_interview_session` 表、3个API端点、前端 `InterviewPanel.vue`。

2. **Boss直聘爬虫+智能推荐** — httpx爬取真实岗位→存库→基于简历LLM推荐Top3。新增 `app/crawler/` 模块、`CrawlerPanel.vue`。

## 生产级优化路线图（Phase 1-4）

> 目标：50+ 并发用户、可评测、高可用、模型可替换的生产级架构。

### Phase 1 — 基础优化（本周，3-4天）

**1.1 模型层重构** (`app/core/llm.py` → `app/core/model_provider.py`)
- 支持多模型：fast（glm-4-flash / qwen-turbo）、primary（glm-4 / deepseek-v3）、fallback
- 模型配置从 `.env` 移到 `model_config.yaml`，包含 provider、name、max_tokens、temperature、base_url
- 每次 LLM 调用支持 `model_key` 参数：`invoke_llm(prompt, model_key="primary")`
- 重试机制：tenacity，3 次指数退避 + 自动切换 fallback 模型
- 并发控制：`asyncio.Semaphore(N)` 限制同时进行的 LLM 调用数
- 意图分类、关键词提取、摘要等轻任务路由到 fast 模型；匹配分析、面试题生成等核心任务用 primary 模型；最终汇总优先模板化，不用模型

**1.2 RAG 优化** (`app/rag/`)
- 瓶颈：`vector_store.search()` 每次查询调一次 embedding API；`retrieve_knowledge_node` 对 10+ 个查询并发调用 → 单次 RAG 耗时 44s
- 方案：小知识库（<50 文件）→ 关键词直接匹配文件名，0 次 API 调用 → <100ms
- 知识库增长后：预计算所有 chunk embedding 离线存储 → search() 只需 1 次 query embedding
- 混合检索：BM25 粗排 + embedding 精排 + Redis 缓存
- 降低召回数量，严格截断 chunk 长度，不命中关键主题时宁可不注入

**1.3 可观测性补齐** (`app/observability/`)
- **致命 bug**：`llm.py` 中 `metrics.record_llm_call(duration_ms=0, ...)` 硬编码 0，所有 LLM 耗时统计失效
- 补全关键指标：`llm_call_duration_ms`（histogram, by model）、`rag_search_duration_ms`、`sse_full_chain_duration_ms`、`task_success_rate`（by task_type）、`tool_error_rate`（by tool_name）、`token_usage_total`（counter）
- Prometheus exporter：`prometheus_fastapi_instrumentator` 一行代码加 HTTP 指标
- 每次 LLM/RAG/SSE 操作记录真实耗时到 OpenTelemetry span

### Phase 2 — 架构升级（下周，4-5天）

**2.1 SQLite → PostgreSQL + Alembic**
- 引入 SQLAlchemy 2.0 async + asyncpg，`sessionmaker` 管理连接池（`pool_size=20, max_overflow=10`）
- `init_db()` → Alembic migration 脚本，版本化管理 schema
- 6 表 → 8 表：新增 `evaluation_run`、`evaluation_result`
- 保留多用户隔离（所有查询已有 `user_id` 过滤）

**2.2 Redis 缓存层**
- L1：进程内 LRU（cachetools, 128 条, TTL 10min）
- L2：Redis（TTL 30min, key = `hash(resume_id + job_id + task_type + prompt_version)`）
- 缓存命中直接返回，Prompt 版本变化自动 miss
- RAG 检索结果也用同样 key 策略缓存

**2.3 后台任务队列** (`app/tasks/` + arq)
- arq（基于 Redis 的轻量 asyncio 任务队列，不需要 Celery）
- Worker 独立进程：`arq app.tasks.WorkerSettings`
- 支持任务类型：`build_rag`（知识库重建）、`eval_run`（批量评测）、`batch_analyze`（批量匹配分析）
- API 模式：`POST /api/eval/run` → enqueue → 返回 `{task_id, status: "queued"}` → `GET /api/eval/run/{task_id}` → 返回进度
- 异步任务通过 SSE 推送进度（复用现有 SSE 管道）

### Phase 3 — 工程化（2周内，4-5天）

**3.1 Prompt 版本管理 + A/B 测试**
- `app/prompts/v1/` → `v1/`（基线）+ `v2/`（实验），`prompt_config.yaml` 控制路由
- A/B 分流：`match_analyze: {default: v2, ab_test: {v1: 10%, v2: 90%}}`
- 每次 LLM 调用在 metadata 中记录 `prompt_version`
- `agent_task` 表新增字段：`prompt_version`、`model_name`、`rag_hit_info`

**3.2 Skill 路由升级** (`app/skills/`)
- 现状：纯关键词子串匹配，0 命中 → embedding fallback → Coordinator LLM（额外一次 LLM 调用）
- 目标：Phase 1（关键词 > 3 分直接路由）→ Phase 2（fast model 分类, ~200ms）→ Phase 3（LLM 路由, 仅 1% 请求）
- 收集 3000 条历史 Copilot 请求（goal + 最终执行的 skill）作为训练数据
- 用 fast model 做 few-shot 分类；目标 95% 请求走 Phase 1/2

**3.3 输出 Schema 标准化**
- LLM 输出 Markdown + 末尾追加隐藏结构化元数据（`<!-- META {"match_score": 70, ...} -->`）
- 前端渲染时过滤 `<!-- META -->` 注释，评测时提取 JSON
- 解决"Markdown 流式展示"和"结构化评测"的矛盾

### Phase 4 — 部署与运维（1天）

**4.1 容器化**
- `docker-compose.yml`：app（FastAPI, uvicorn 4 workers）+ postgres（15）+ redis（7）+ arq-worker（2 workers）+ nginx + prometheus + grafana
- Nginx 反向代理 + 限流（`limit_req_zone` 每 IP 10 req/s）

**4.2 Grafana 仪表盘**
- LLM 耗时分位图（P50/P95/P99, by model）
- RAG 命中率趋势、task success rate、tool error rate
- SSE 全链路耗时分布

### 性能目标

| 指标 | 当前 | 目标 |
|------|------|------|
| "全面备战"全链路 | ~165s | <30s |
| RAG 检索 | ~44s | <1s |
| LLM 调用次数/请求 | 3 次 | 2 次（合并 match+optimize） |
| 并发用户 | 1 | 50 |
| LLM 调用成功率 | 无统计 | >99% |
| 缓存命中率 | 0% | >60% |

### 关键架构决策

- **不引入 Celery**：arq 基于 Redis + asyncio，与 FastAPI 技术栈一致，零新依赖范式
- **先监控后优化**：Phase 1 补全观测指标，收集一周真实数据后再决定 PG 迁移的紧迫性
- **Prompt 版本强绑定**：每次 LLM 调用的 `prompt_version` + `model_name` + `rag_hit_info` 打入 `agent_task` 元数据，可回答"为什么今天结果比昨天好/差"
- **缓存 key 包含 prompt_version**：改 Prompt 时自动破缓存，避免旧缓存污染新 Prompt 的对比实验
- **模型路由而非模型锁定**：不绑定单一模型，按 task_type 路由到不同模型，支持 fallback 降级
