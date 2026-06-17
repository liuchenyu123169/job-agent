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

## 待实现功能

1. **AI模拟面试** — 多轮对话：出题→用户回答→评估打分→追问→最终报告。新增 `mock_interview_session` 表、3个API端点、前端 `InterviewPanel.vue`。

2. **Boss直聘爬虫+智能推荐** — httpx爬取真实岗位→存库→基于简历LLM推荐Top3。新增 `app/crawler/` 模块、`CrawlerPanel.vue`。

兜底怎么做的，skill格式怎么回事，会话记忆