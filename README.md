# JobAgent - AI 求职 Copilot 系统

JobAgent 是一个面向求职场景的 AI Copilot 系统，旨在帮助用户完成从简历管理、岗位分析、简历优化、面试准备到岗位推荐的完整求职流程。系统不是简单调用大模型生成文本，而是将简历解析、岗位管理、匹配分析、RAG 知识检索、面试题生成、岗位推荐等能力封装为标准化 Tool，并通过 LangGraph Agent 进行智能编排，实现面向求职任务的自动化执行。

## 一、项目定位

JobAgent 的目标是从传统的“AI 功能集合”升级为“AI 求职 Copilot”。

传统模式下，用户需要手动点击多个功能入口，例如先上传简历，再保存岗位，再点击匹配分析、简历优化、面试题生成等按钮。而 Copilot 模式下，用户只需要用自然语言表达目标，例如：

```text
帮我全面准备这个后端开发岗位的面试
```

系统会自动识别用户意图，并根据当前简历、目标岗位和知识库内容，自动调用多个工具完成完整任务链路。

核心能力包括：

```text
用户注册登录
用户数据隔离
简历上传解析
岗位 JD 管理
岗位匹配分析
简历优化建议
RAG 增强面试题生成
岗位推荐
任务记录
LangGraph Tool 调用
SSE 流式执行进度
Copilot 会话管理
```

## 二、核心功能

### 1. 用户体系与数据隔离

系统支持用户注册、登录和 JWT 鉴权。每个用户只能访问自己的简历、岗位、AI 任务记录和推荐结果。

数据隔离字段包括：

```text
resume.user_id
job.user_id
agent_task.user_id
```

同时系统支持用户内编号：

```text
resume.local_resume_id
job.local_job_id
```

数据库内部仍使用全局唯一 ID，前端展示时使用用户视角下从 1 开始的本地编号，提升使用体验。

### 2. 简历上传与解析

用户可以上传个人简历，系统会解析简历文本内容，并保存到数据库中，作为后续岗位匹配、简历优化和面试题生成的基础数据。

### 3. 岗位 JD 管理

用户可以保存目标岗位 JD，系统会记录岗位名称、公司、岗位描述、技能要求等信息。后续所有分析任务都围绕简历和岗位 JD 展开。

### 4. 岗位匹配分析

系统基于用户简历和岗位 JD，调用大模型分析匹配度，输出内容包括：

```text
匹配分数
匹配优势
能力短板
技能差距
优化建议
```

该功能可以帮助用户判断当前岗位是否适合自己，以及后续应该重点补充哪些能力。

### 5. 简历优化建议

系统会结合目标岗位要求，对用户简历提出针对性优化建议，包括项目描述、技能关键词、表达方式和岗位匹配度提升方向。

### 6. RAG 面试知识库

系统内置 RAG 知识库模块，支持构建和检索面试相关知识内容。知识库内容覆盖：

```text
Java
MySQL
Redis
Agent
RAG
LangGraph
```

RAG 链路包括：

```text
本地知识文档
→ 文档清洗
→ 结构化切分
→ Embedding 向量化
→ Chroma 持久化
→ 多路检索
→ 知识片段召回
```

RAG 的主要作用是让面试题生成不只依赖简历和 JD，而是结合后端八股、数据库、缓存、AI Agent 等知识库内容，生成更具体、更贴近面试场景的问题。

### 7. RAG 增强面试题生成

系统支持开启或关闭 RAG：

```text
enable_rag = false：简历 + JD + Prompt + LLM
enable_rag = true ：简历 + JD + RAG 知识片段 + Prompt + LLM
```

开启 RAG 后，系统可以生成更具体的技术追问，例如：

```text
MySQL InnoDB 为什么选择 B+Tree 作为索引结构？
Redis 如何实现分布式锁？有哪些缺点？
LangGraph 中多节点 Agent 工作流如何实现？
```

### 8. 岗位推荐

系统支持根据用户的一份简历，对用户保存过的多个岗位逐个进行匹配分析，并按照匹配分数排序，返回 TopK 推荐岗位。

该功能将系统从“分析单个岗位”升级为“从岗位库中推荐最适合用户的岗位”。

### 9. AI Copilot 工具调用

系统后续会将已有能力封装为标准化 Tool，例如：

```text
match_analyze
optimize_resume
generate_interview_questions
recommend_jobs
search_knowledge
list_resumes
list_jobs
get_task
```

每个 Tool 统一包含：

```text
name
description
parameters
async execute()
```

Tool 会注册到 ToolRegistry 中，供 LangGraph Agent 动态调用。

### 10. LangGraph ReAct Agent 编排

Copilot 的核心编排层使用 LangGraph 实现。系统会通过 ReAct Agent 进行工具调用决策：

```text
用户目标
→ LLM Planner 判断需要调用哪些工具
→ ToolNode 执行工具
→ 工具结果返回给 Agent
→ Agent 判断是否继续调用工具
→ 输出最终总结
```

示例任务：

```text
帮我全面备战某个后端开发岗位
```

系统可能自动执行：

```text
读取简历
→ 读取岗位
→ 匹配分析
→ 简历优化
→ RAG 检索
→ 面试题生成
→ 保存任务
→ 输出最终准备报告
```

### 11. SSE 流式 Copilot API

为了提升用户体验，系统计划使用 SSE 实现流式任务进度推送。用户执行 Copilot 任务时，前端可以实时展示：

```text
正在分析简历与岗位匹配度...
正在检索 RAG 知识库...
正在生成面试题...
正在生成最终总结...
任务完成
```

后端事件类型包括：

```text
plan
step_start
step_complete
step_error
final
```

### 12. Copilot 会话管理

系统计划引入 Copilot Session，用于保存用户的一次完整 Copilot 执行上下文，包括：

```text
用户目标
执行状态
上下文数据
工具调用记录
关联任务 ID
创建时间
更新时间
```

后续可以支持会话恢复、历史查询和多轮上下文延续。

## 三、技术栈

### 后端

```text
Python
FastAPI
LangGraph
LangChain
JWT
SQLite / 可扩展至 MySQL、PostgreSQL
Chroma
Pydantic
```

### AI 能力

```text
GLM 大模型
Embedding 模型
RAG 检索
Function Calling / Tool Calling
LangGraph ToolNode
ReAct Agent
```

### 前端

```text
Vue
Vite
Dashboard 页面
任务结果展示
Copilot 对话入口
SSE 流式进度展示
```

### 工程能力

```text
模块化目录结构
用户数据隔离
工具注册中心
异步 Tool 执行
任务记录
接口鉴权
异常处理
日志记录
```

## 四、系统架构

整体架构分为五层：

```text
前端 Dashboard / Copilot 页面
        ↓
Copilot API / SSE 流式接口
        ↓
LangGraph Agent / Pipeline 编排层
        ↓
Tool Registry / 标准化工具层
        ↓
现有业务能力：简历、岗位、RAG、LLM、任务记录、数据库
```

目标架构：

```text
用户自然语言目标
        ↓
Copilot API
        ↓
LangGraph ReAct Agent
        ↓
ToolNode 调用工具
        ↓
匹配分析 / 简历优化 / RAG 检索 / 面试题生成 / 岗位推荐
        ↓
SSE 推送执行进度
        ↓
最终求职准备报告
```

## 五、目录规划

```text
app/
  api/
    auth_api.py
    resume_api.py
    job_api.py
    agent_api.py
    knowledge_api.py
    copilot_api.py
    stream_utils.py

  core/
    config.py
    llm.py
    security.py

  db/
    database.py
    crud.py
    models.py

  rag/
    rag_service.py
    knowledge_builder.py

  tools/
    __init__.py
    base.py
    registry.py
    match_analyze_tool.py
    optimize_resume_tool.py
    interview_questions_tool.py
    recommend_jobs_tool.py
    utility_tools.py

  copilot/
    __init__.py
    state.py
    graph.py
    prompts.py
    summarizer.py

  schemas/
    user_schema.py
    resume_schema.py
    job_schema.py
    copilot_schema.py
```

## 六、Copilot 改造计划

### 阶段 0：安全修复与基础清理

目标是在不改变现有功能的前提下，修复基础安全和代码质量问题。

计划包括：

```text
JWT 默认密钥检测
注册密码最小长度校验
任务排序字段白名单
空白文件检查与清理
```

### 阶段 1：Tool 抽象层

目标是建立统一的工具协议和工具注册中心。

主要内容：

```text
定义 ToolDefinition
定义 ToolResult
实现 ToolRegistry
封装 match_analyze Tool
封装 optimize_resume Tool
封装 generate_interview_questions Tool
封装 recommend_jobs Tool
封装 search_knowledge / list_resumes / list_jobs 等辅助 Tool
```

阶段完成标志：

```text
ToolRegistry 可以返回全部可用 Tool
每个 Tool 可以被独立调用
每个 Tool 返回统一格式结果
```

### 阶段 2：LangGraph Pipeline 编排引擎

目标是基于 LangGraph 实现 ReAct Agent，让系统可以根据用户目标动态调用工具。

主要内容：

```text
定义 PipelineContext
定义 PipelineState
编写 Copilot System Prompt
实现 Copilot Graph
实现 LLM with Tools 调用
实现 ToolNode 执行逻辑
实现最终结果汇总
```

阶段完成标志：

```text
输入一句自然语言目标后，系统能够自动调用多个 Tool，并返回完整结果。
```

### 阶段 3：SSE 流式 Copilot API

目标是让前端实时看到 Copilot 执行进度。

主要内容：

```text
定义 SSE 事件格式
新增 POST /api/copilot/run
对接 LangGraph astream_events
推送 step_start / step_complete / final 等事件
处理工具异常和 LLM 异常
```

阶段完成标志：

```text
前端或 curl 可以看到任务执行过程的流式输出。
```

### 阶段 4：会话管理

目标是保存 Copilot 执行历史和上下文。

主要内容：

```text
新增 copilot_session 表
实现 create_session / get_session / list_sessions / update_session
新增会话查询 API
保存工具调用记录和任务结果
```

阶段完成标志：

```text
用户可以查看历史 Copilot 会话，并恢复某次任务结果。
```

## 七、典型使用流程

### 1. 用户上传简历

```text
用户登录系统
→ 上传简历文件
→ 系统解析简历内容
→ 保存为用户简历记录
```

### 2. 用户保存岗位

```text
用户输入或粘贴岗位 JD
→ 系统保存岗位信息
→ 生成用户内 local_job_id
```

### 3. 用户发起 Copilot 任务

用户输入：

```text
帮我全面准备这个岗位的面试
```

系统自动执行：

```text
读取当前简历
→ 读取目标岗位
→ 分析匹配度
→ 检索知识库
→ 生成面试题
→ 生成准备建议
→ 保存任务记录
→ 返回最终报告
```

### 4. 前端展示执行过程

通过 SSE 实时展示：

```text
开始规划任务
正在执行匹配分析
正在执行 RAG 检索
正在生成面试题
正在汇总结果
任务完成
```

## 八、接口规划

### Copilot 运行接口

```http
POST /api/copilot/run
```

请求示例：

```json
{
  "goal": "帮我全面备战这个后端开发岗位",
  "resume_id": 1,
  "job_id": 1
}
```

SSE 返回示例：

```text
event: plan
data: {"steps": ["match_analyze", "search_knowledge", "generate_interview_questions"]}

event: step_start
data: {"tool": "match_analyze"}

event: step_complete
data: {"tool": "match_analyze", "success": true}

event: final
data: {"summary": "完整面试准备结果"}
```

### 会话列表接口

```http
GET /api/copilot/sessions
```

### 会话详情接口

```http
GET /api/copilot/sessions/{session_id}
```

## 九、项目亮点

### 1. 从单点 AI 功能升级为 Copilot

系统不是简单提供多个按钮，而是通过 Copilot 编排多个能力，完成完整求职任务。

### 2. 工具层标准化

将岗位匹配、简历优化、RAG 检索、面试题生成等能力封装成统一 Tool，为后续扩展更多能力打基础。

### 3. LangGraph Agent 编排

通过 LangGraph ReAct Agent 实现动态工具调用，使系统具备更强的任务规划能力。

### 4. RAG 增强生成

面试题生成不只依赖大模型通用知识，而是结合本地技术知识库，提高生成内容的针对性和技术深度。

### 5. SSE 流式体验

任务执行过程可以实时推送给前端，用户能够看到每一步执行状态，而不是长时间等待空白页面。

### 6. 用户数据隔离

系统支持多用户独立使用，每个用户有自己的简历、岗位和任务记录，具备 SaaS 化基础。

## 十、后续优化方向

后续可以继续扩展：

```text
多轮 Copilot 对话
任务中断与恢复
Human-in-the-loop 确认机制
批量岗位对比
求职信生成
投递邮件生成
面试日程管理
更完善的 Trace 可视化
LLM 调用重试与降级
用户级限流
异步任务队列
Docker 部署
```

## 十一、项目总结

JobAgent 是一个面向求职场景的 AI Copilot 系统。系统通过用户体系、简历解析、岗位管理、RAG 知识库和 AI 分析能力，帮助用户完成岗位匹配、简历优化、面试题生成和岗位推荐。后续通过 Tool 抽象层、LangGraph ReAct Agent、SSE 流式接口和会话管理，将系统从普通 AI 求职助手升级为可自动编排复杂任务的 AI 求职 Copilot。
