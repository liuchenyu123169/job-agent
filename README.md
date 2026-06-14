# JobAgent AI求职助手系统
## 项目简介：

JobAgent 是一个面向实习求职场景的 AI 应用系统。
用户可以录入简历和岗位 JD。
系统会基于大模型分析简历与岗位的匹配度。
同时给出优势、不足和简历优化建议。
系统会保存每次分析任务，方便后续查看和复盘。

## 项目背景：

求职过程中，很多同学不知道自己的简历和岗位要求是否匹配。
岗位 JD 往往信息很多，人工分析效率低。
简历优化也容易缺少针对性。
因此设计一个 AI 求职助手，根据简历和 JD 自动分析匹配情况，并给出修改建议。

## 核心功能：

### 已实现功能：
简历管理：支持保存和查询简历文本。\
岗位管理：支持保存和查询岗位 JD。\
AI 匹配分析：根据 resume_id 和 job_id，分析简历与岗位的匹配度。\
简历优化建议：根据岗位要求，生成针对性的简历修改建议。\
任务记录：保存每次 AI 分析任务的输入、输出、状态和错误信息。\
接口文档：基于 FastAPI 自动生成 Swagger 文档。 \
新增任务列表查询接口，支持按任务类型、简历 ID、岗位 ID 查询历史 AI 任务记录，
方便查看岗位匹配分析、简历优化建议和面试题生成等任务结果。 \
新增简历文件上传解析能力，支持上传 PDF、Word 或 TXT 简历文件，
后端自动解析简历文本并保存到 resume 表，后续可直接复用 resume_id 进行岗位匹配分析、简历优化建议和面试题生成。

### 后续规划功能：
LangGraph 多节点 Agent 工作流，
RAG 面试知识库，
SSE 流式响应，
PDF / DOCX 简历解析，
前端页面，
线上部署

## 技术栈：
后端框架：FastAPI \
AI 编排：LangChain \
大模型调用：OpenAI Compatible API \
数据存储：SQLite \
参数校验：Pydantic \
接口文档：Swagger / OpenAPI \
开发语言：Python

## 核心流程

### 简历保存流程
用户提交简历文本
↓
FastAPI 接收请求
↓
Pydantic 校验 file_name 和 content
↓
调用 insert_resume 写入 SQLite
↓
返回 resume_id
### 岗位保存流程
用户提交岗位公司、标题和 JD 文本
↓
FastAPI 接收请求
↓
Pydantic 校验参数
↓
调用 insert_job 写入 SQLite
↓
返回 job_id
### AI 匹配分析流程
用户提交 resume_id 和 job_id
↓
系统查询简历内容和岗位 JD
↓
组装匹配分析 Prompt
↓
调用大模型生成分析结果
↓
保存 agent_task 任务记录
↓
返回 task_id 和分析结果