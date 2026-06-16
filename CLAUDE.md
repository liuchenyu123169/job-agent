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

- **后端**: FastAPI + LangGraph + LangChain + SQLite + ChromaDB + JWT + Jinja2 + PyYAML
- **前端**: Vue 3 (SPA, Vite, `frontend/src/components/` 7个SFC)
- **LLM**: 智谱 GLM (`glm-4-flash`) 通过 LangChain `ChatOpenAI`

## 架构分层（从上到下）

```
用户输入
  ↓ ChatPanel.send() → resolveIntent() 匹配 Skill
  ↓ POST /api/copilot/run {mode, goal, resume_id, job_id}
  ↓
Copilot API — 三种模式:
  fast       → 跳过LLM, 按 tools[] 顺序直跑
  react      → 单ReAct Agent, 8个原子工具平铺
  coordinator → Coordinator + 3子Agent 层次化委派
  ↓
Skill 系统 (app/skills/) → YAML配置, 关键词匹配用户意图, 决定mode+sub_agents
  ↓
Coordinator (ReAct) → 委派子Agent(也是ToolDefinition)
  ↓ 子Agent内部是 LangGraph pipeline (复用 workflow.py 节点)
  ↓
LLM调用前: PromptManager.render() → Jinja2模板 + FewShot注入
  ↓
LLM / RAG / DB
```

## 关键模块

| 模块 | 路径 | 作用 |
|------|------|------|
| Prompt引擎 | `app/prompt_engine/` | PromptManager(Jinja2加载/渲染/版本切换) + FewShotStore(YAML示例库) + PromptEvaluator(AB对比) |
| 多Agent | `app/agents/` | Coordinator(ReAct调度者) + ResumeAgent + InterviewAgent + SearchAgent |
| Skill系统 | `app/skills/` | SkillRegistry(YAML加载/关键词匹配) + 4个skill配置 |
| 工具层 | `app/tools/` | ToolDefinition + ToolRegistry全局单例, 8个工具 |
| Workflow | `app/agent/workflow.py` | 3个LangGraph StateGraph + run_*_workflow() |
| Copilot | `app/copilot/` | ReAct graph + PipelineContext + summarizer + system_prompt |
| RAG | `app/rag/` | loader→cleaner→splitter→embedding→ChromaDB |
| 数据库 | `app/db/` | SQLite 5表: user/resume/job/agent_task/copilot_session |

## 新增功能的标准流程

1. 写 Jinja2 模板 → `app/prompts/v1/xxx.j2`
2. (可选) 写 few-shot → `app/prompts/few_shots/xxx.yaml`
3. (可选) 写测试用例 → `app/prompts/eval_cases/xxx.yaml`
4. 写 workflow → `app/agent/workflow.py` 加 StateGraph + run函数
5. 写 tool → `app/tools/xxx_tool.py` (ToolDefinition + keywords + render_type)
6. 注册 → `app/tools/__init__.py` 加 import
7. 如需Skill编排 → `app/skills/xxx.yaml`

注册后 system_prompt、`/api/copilot/tools`、`/api/copilot/skills` 全部自动感知。

## 重要约定

- 前端组件用 Vue `provide`/`inject` 共享状态
- 所有 Tool.execute 必须 async, 返回 ToolResult
- 所有 workflow 共用 `AgentAnalyzeState` TypedDict (20字段)
- 子Agent从Coordinator视角看就是ToolDefinition (`_wrap_sub_agent_tool()`)
- 模板用 Jinja2 `{{ var }}` 语法, 不再用 `.format()`
- 前端SSE解析在 api.js `streamCopilot()` (POST+fetch+ReadableStream)
