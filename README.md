# JobAgent

JobAgent 是一个面向求职场景的 AI Copilot 项目，提供简历管理、岗位管理、岗位匹配分析、简历优化、面试题生成、岗位推荐，以及带流式输出的 Copilot 对话体验。

当前仓库已经完成过一轮较大的架构重构。本文档基于现在的代码目录、接口入口和运行方式整理，重点帮助你快速理解项目、启动项目、继续开发。

## 当前能力

- 用户注册、登录、JWT 鉴权
- 简历上传、解析、存储与管理
- 岗位 JD 录入、管理与推荐
- 简历与岗位的匹配分析
- 面向目标岗位的简历优化与定制化生成
- 基于知识库的 RAG 检索与面试题生成
- Copilot 对话式任务执行，支持 SSE 流式返回
- 闭环编排器：`plan -> precheck -> execute -> verify -> replan -> finalize`
- 管理后台、评测页、任务追踪、会话历史
- PostgreSQL 持久化、Redis 可选缓存、Chroma 向量库

## 技术栈

- 后端：FastAPI
- 前端：Vue 3 + Vite
- 模型与编排：OpenAI SDK / LangGraph / 自定义 Orchestrator
- 数据库：PostgreSQL
- 向量存储：ChromaDB
- 缓存与任务：Redis、arq
- 评测：内置 evaluation runner + LLM judge

## 项目结构

现在的后端已经不是旧版 `app/agents + app/workflows + app/core` 那套布局，核心目录如下：

```text
app/
  main.py                     FastAPI 入口
  api/                        所有 HTTP API
  application/                Copilot 编排、工作流、闭环调度
  ai/                         LLM、Prompt、RAG、Skill 路由
  domain/                     领域逻辑
  infrastructure/             DB、缓存、外部搜索、外部岗位抓取、后台任务
  shared/                     配置、Schema、状态对象、可观测性、工具函数
  tools/                      Copilot 可调用工具

frontend/
  src/
    pages/                    用户页与管理后台页面
    components/               通用组件
    api/                      前端 API 封装

tests/                        当前测试用例
docs/                         设计文档
data/                         知识库与向量库数据目录
evaluation_results/           评测输出目录
```

## 后端架构概览

### 1. API 层

主要入口在 [app/main.py](/D:/python-learn/PythonProject/job-agent/app/main.py)。

已挂载的核心路由包括：

- `/api/auth`：注册、登录、当前用户
- `/api/resume`：简历上传与管理
- `/api/job`：岗位管理
- `/api/knowledge`：知识库与 RAG 数据
- `/api/copilot`：Copilot 对话、会话历史、工具和技能发现
- `/api/agent-runs`：闭环任务执行状态
- `/api/task`、`/api/tasks`：任务记录与后台任务
- `/api/evaluation`：评测接口
- `/api/admin`：管理后台接口
- `/health`：健康检查
- `/metrics`：Prometheus 指标暴露

### 2. Copilot 路由方式

Copilot 入口在 [app/api/copilot_api.py](/D:/python-learn/PythonProject/job-agent/app/api/copilot_api.py)。

当前有两条主要执行路径：

- 明确意图命中 Skill 时，走 `direct_tools`，按固定工具链执行
- 开放式目标或复杂任务时，走 `ClosedLoopOrchestrator.run_stream()`，进入闭环编排

### 3. 闭环编排器

核心实现位于 [app/application/orchestrator.py](/D:/python-learn/PythonProject/job-agent/app/application/orchestrator.py)。

它负责：

- 规划步骤
- 前置条件检查
- 工具执行
- 结果验证
- 失败后重新规划
- 汇总最终报告

这也是当前项目最重要的架构升级点。

## 前端结构概览

前端入口在 [frontend/src/App.vue](/D:/python-learn/PythonProject/job-agent/frontend/src/App.vue)。

当前前端包含两类页面：

- 用户侧：对话、简历、岗位、推荐、任务
- 管理侧：仪表盘、用户、简历、岗位、任务、会话、链路追踪、知识库、评测

Copilot 页面支持：

- 会话切换
- 历史对话恢复
- SSE 流式展示
- 当前简历 / 当前岗位上下文联动

## 快速开始

### 1. 环境要求

- Python 3.11+ 推荐
- Node.js 20+ 推荐
- PostgreSQL 15
- Redis 7 可选

### 2. 安装后端依赖

```bash
pip install -r requirements.txt
```

### 3. 配置环境变量

复制并编辑环境文件：

```bash
cp .env.example .env
```

当前代码实际会用到的主要变量包括：

- `DATABASE_URL`
- `JWT_SECRET_KEY`
- `JWT_ALGORITHM`
- `JWT_EXPIRE_MINUTES`
- `ZHIPU_API_KEY`
- `ZHIPU_BASE_URL`
- `DEEPSEEK_API_KEY`
- `EMBEDDING_MODEL`
- `KNOWLEDGE_DIR`
- `CHROMA_DIR`
- `CHROMA_COLLECTION_NAME`
- `REDIS_URL`
- `BOCHA_API_KEY`
- `BOCHA_BASE_URL`
- `BAZHUA_API_KEY`
- `BAZHUA_BASE_URL`

其中：

- `DATABASE_URL` 为必填
- `REDIS_URL` 可不填，缓存层会按无缓存模式降级
- `BOCHA_*` 和 `BAZHUA_*` 是公开搜索 / 网页抓取相关的可选外部能力

### 4. 启动基础设施

仓库已提供 PostgreSQL 和 Redis 的 `docker-compose.yml`：

```bash
docker-compose up -d
```

默认端口：

- PostgreSQL：`5432`
- Redis：`6379`

### 5. 初始化数据库

```bash
alembic upgrade head
```

### 6. 启动后端

```bash
python -m uvicorn app.main:app --reload --port 8000
```

启动后默认访问：

- API: [http://127.0.0.1:8000](http://127.0.0.1:8000)
- 健康检查: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)
- OpenAPI: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

### 7. 启动前端

```bash
cd frontend
npm install
npm run dev
```

默认前端地址：

- [http://127.0.0.1:5173](http://127.0.0.1:5173)

## 评测

项目内置了评测模块，入口在 [app/evaluation/__main__.py](/D:/python-learn/PythonProject/job-agent/app/evaluation/__main__.py)。

命令行示例：

```bash
python -m app.evaluation --workflow match_analyze
```

可选 workflow：

- `match_analyze`
- `interview_questions`
- `resume_optimize`
- `resume_generate`

评测结果会写入 `evaluation_results/`。

## 测试

当前仓库中已有的测试主要集中在：

- 路由 / Skill 匹配
- 编排器参数与前置检查
- Summarizer
- 外部工具

测试目录见 [tests](/D:/python-learn/PythonProject/job-agent/tests)。

如果本地已安装 `pytest`，可以尝试：

```bash
pytest tests
```

## 设计文档

仓库里已有一份闭环编排设计说明：

- [docs/agent-closed-loop-design.md](/D:/python-learn/PythonProject/job-agent/docs/agent-closed-loop-design.md)

如果你要继续重构 Copilot 或任务系统，建议优先读这份文档，再结合 `app/application/orchestrator.py` 和 `app/api/copilot_api.py` 一起看。

## 当前阅读建议

如果你刚接手这个项目，建议按下面顺序阅读：

1. [app/main.py](/D:/python-learn/PythonProject/job-agent/app/main.py)
2. [app/api/copilot_api.py](/D:/python-learn/PythonProject/job-agent/app/api/copilot_api.py)
3. [app/application/orchestrator.py](/D:/python-learn/PythonProject/job-agent/app/application/orchestrator.py)
4. [app/tools](/D:/python-learn/PythonProject/job-agent/app/tools)
5. [app/ai/skills](/D:/python-learn/PythonProject/job-agent/app/ai/skills)
6. [frontend/src/App.vue](/D:/python-learn/PythonProject/job-agent/frontend/src/App.vue)

## 说明

这次更新 README 的目标不是保留历史设计，而是让文档和当前代码结构对齐。如果后续继续重构目录，优先同步更新以下内容：

- `app/` 下的实际模块路径
- 启动命令
- 环境变量
- Copilot 的执行路径
- 前端页面结构
