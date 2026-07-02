# -*- coding: utf-8 -*-
"""Quick routing test — verify skill matching works correctly."""
import sys
sys.path.insert(0, ".")

from app.skills.registry import skill_registry

test_goals = [
    ("分析我和这个岗位的匹配度", "match_analyze", "Fixed Workflow"),
    ("优化我的简历", "optimize_resume", "Fixed Workflow"),
    ("帮我生成面试题", "interview_prep", "Fixed Workflow"),
    ("全面备战字节后端岗", "full_prep", "Fixed Workflow"),
    ("帮我生成一份定制简历", "custom_resume", "Fixed Workflow"),
    ("推荐几个适合我的岗位", "find_jobs", "Orchestrator"),
    ("对比阿里P7和字节2-2的技术栈", None, "Orchestrator"),
    ("复盘上次的面试表现", None, "Orchestrator"),
    ("两周内提升到P6水平", None, "Orchestrator"),
]

print("=" * 70)
print(f"{'Goal':35s} {'Skill':20s} {'Route':16s} {'OK'}")
print("-" * 70)

all_ok = True
for goal, expected_skill, expected_route in test_goals:
    skills = skill_registry.match_all(goal)
    workflow = [s for s in skills if s.mode == "workflow"]
    closed_loop = [s for s in skills if s.mode == "closed_loop"]

    actual_route = "Fixed Workflow" if workflow else "Orchestrator"
    top_skill = workflow[0].name if workflow else (closed_loop[0].name if closed_loop else "none")

    route_ok = actual_route == expected_route
    skill_ok = (expected_skill is None) or (top_skill == expected_skill)
    ok = "OK" if (route_ok and skill_ok) else "FAIL"

    if not (route_ok and skill_ok):
        all_ok = False
        print(f"{goal:35s} {top_skill:20s} {actual_route:16s} {ok} (expected: {expected_route}/{expected_skill})")
    else:
        print(f"{goal:35s} {top_skill:20s} {actual_route:16s} {ok}")

print("-" * 70)
print("ALL TESTS PASSED" if all_ok else "SOME TESTS FAILED")
