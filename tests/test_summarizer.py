from app.copilot.state import PipelineContext
from app.copilot.summarizer import summarize_result


def test_summarize_result_handles_string_payloads():
    context = PipelineContext(resume_id=1, job_id=2)
    context.executed_tools = [
        "match_analyze",
        "optimize_resume",
        "generate_interview_questions",
    ]
    context.tool_results = {
        "match_analyze": {
            "task_id": 11,
            "analysis": "匹配度 65 分，Linux 底层与分布式存储存在短板。",
        },
        "optimize_resume": {
            "task_id": 12,
            "optimization": "已补充监控观测、APM 和项目量化表述。",
        },
        "generate_interview_questions": {
            "task_id": 13,
            "questions": "1. 解释 eBPF 在 APM 中的作用。\n2. 如何定位线上性能抖动？",
        },
    }
    context.task_ids = [11, 12, 13]

    report = summarize_result(context)

    assert "匹配分析" in report["summary"]
    assert "简历优化" in report["summary"]
    assert "面试题已生成" in report["summary"]
    assert len(report["steps"]) == 3
