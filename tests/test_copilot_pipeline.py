"""端到端 Copilot Pipeline 手动测试脚本。

使用方法：
    python tests/test_copilot_pipeline.py

前提条件：
    1. .env 中有有效的 LLM API key
    2. 数据库中有简历和岗位数据（先通过前端或 API 上传）
    3. 服务未运行（避免 SQLite 锁冲突）
"""

import asyncio
import json
import sys

from langchain_core.messages import HumanMessage

from app.copilot.graph import copilot_graph
from app.copilot.state import PipelineContext, PipelineState
from app.copilot.summarizer import summarize_result


async def run_test() -> None:
    """运行一次完整的 Copilot Pipeline。"""
    print("=" * 60)
    print("  JobAgent Copilot Pipeline 端到端测试")
    print("=" * 60)

    # ── 配置：修改这里的 ID 为你数据库中实际的简历和岗位 ID ──
    RESUME_ID = 1
    JOB_ID = 1
    USER_ID = 1

    # 用户输入的目标描述
    user_goal = f"帮我全面备战这个岗位。我的简历 ID 是 {RESUME_ID}，岗位 ID 是 {JOB_ID}。请依次做匹配分析、简历优化、面试题生成。"

    print(f"\n用户目标: {user_goal}")
    print(f"简历 ID: {RESUME_ID}, 岗位 ID: {JOB_ID}, 用户 ID: {USER_ID}")
    print("")

    # 构建初始状态
    context = PipelineContext(resume_id=RESUME_ID, job_id=JOB_ID)
    initial_state: PipelineState = {
        "messages": [HumanMessage(content=user_goal)],
        "context": context,
        "user_id": USER_ID,
    }

    print("开始执行 Copilot Pipeline...\n")

    try:
        # 使用 ainvoke 运行异步 Graph
        final_state = await copilot_graph.ainvoke(
            initial_state,
            config={"recursion_limit": 20},  # 允许足够多的循环次数
        )

        ctx: PipelineContext = final_state["context"]
        messages = final_state["messages"]

        # 获取 LLM 最终回复
        final_text = ""
        if messages and hasattr(messages[-1], "content"):
            final_text = str(messages[-1].content or "")

        # 生成结构化报告
        report = summarize_result(ctx, final_message=final_text)

        print("\n" + "=" * 60)
        print("  执行结果")
        print("=" * 60)
        print(f"\nLLM 最终回复:\n{final_text}\n")
        print(f"执行步骤: {' → '.join(report['executed_tools'])}")
        print(f"任务 ID 列表: {report['task_ids']}")
        print(f"\n步骤详情:")
        for step in report["steps"]:
            print(f"  - {step}")

        print("\n✅ Pipeline 执行成功!")

    except Exception as exc:
        print(f"\n❌ Pipeline 执行失败: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run_test())
