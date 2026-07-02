# Agent 闭环架构设计

> 目标：从"AI 功能集合"升级为"会持续推进求职任务的 Agent 系统"

## 最终用户体验目标

```
用户：帮我准备这个后端岗位

系统不会只返回一段分析，而是自己推进完整链路：
  1. 检查有没有简历、岗位 JD、知识库          ← precheck
  2. 自动生成计划                              ← planner
  3. 先做匹配分析                              ← executor
  4. 如果分数低，自动做简历优化                 ← executor + conditional
  5. 优化后重新评分                            ← executor + verifier
  6. 针对短板检索知识点                        ← executor
  7. 生成定制面试题                            ← executor
  8. 验证所有输出质量                          ← verifier
  9. 不达标 → 重规划 → 再执行                  ← replanner
  10. 输出最终备战报告和下一步建议              ← finalizer

如果中间缺信息，不是报错结束，而是明确告诉用户：
  - 现在卡在哪
  - 还缺什么
  - 补完后会继续做什么
```

## 五层改造方案

### 第 1 层：状态层 — PipelineState → TaskState

**文件**: `app/copilot/state.py`

新增 `TaskState` 数据类，与现有的 `PipelineState`（执行上下文）并存：

```python
@dataclass
class TaskState:
    """任务推进状态 — 记录"任务做到哪了、为什么没完成、下一步干什么"。

    与 PipelineContext 的区别：
      - PipelineContext: 执行上下文（选了哪个简历、调了哪些工具）
      - TaskState: 任务状态机（目标、计划、进度、阻塞、验收）
    """

    # ── 目标 ──
    goal: str = ""
    goal_type: str = ""  # prepare / compare / optimize / review / plan
    goal_status: str = "created"  # created → planning → running → blocked → verifying → completed → failed

    # ── 计划 ──
    plan_steps: list[dict] = field(default_factory=list)
    # 每步: {id, name, description, depends_on:[], status:pending|running|done|skipped|failed,
    #        acceptance_criteria, verification_result, assigned_agent}

    current_step: str = ""       # 当前正在执行的 step id
    completed_steps: list[str] = field(default_factory=list)
    pending_steps: list[str] = field(default_factory=list)
    failed_steps: list[str] = field(default_factory=list)

    # ── 阻塞 ──
    blockers: list[dict] = field(default_factory=list)
    # 每项: {type: missing_input|low_quality|external|user_action,
    #        description, resolution_hint, resolved:bool}

    # ── 下一步 ──
    next_action: str = ""        # 面向用户的下一步行动描述

    # ── 验收 ──
    acceptance_criteria: list[str] = field(default_factory=list)
    verification_results: list[dict] = field(default_factory=list)
    # 每项: {step_id, criteria, passed:bool, score, detail, suggested_fix}

    # ── 重规划 ──
    replan_count: int = 0
    max_replan: int = 3

    # ── 最终输出 ──
    final_report: str = ""
    next_suggestions: list[str] = field(default_factory=list)

    def is_blocked(self) -> bool:
        return len(self.blockers) > 0 and all(not b.get("resolved") for b in self.blockers)

    def all_verified(self) -> bool:
        if not self.verification_results:
            return False
        return all(v.get("passed") for v in self.verification_results)

    def needs_replan(self) -> bool:
        return (not self.all_verified() and self.replan_count < self.max_replan)
```

### 第 2 层：数据库层 — 新增 agent_run 表

**职责分离**:
- `copilot_session` — "聊过什么"（对话历史）
- `agent_run` — "任务做到哪了"（任务推进状态）

```sql
CREATE TABLE agent_run (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    session_id INTEGER,              -- 关联的会话（可选，独立任务不需要）

    -- 目标
    goal TEXT NOT NULL,
    goal_type TEXT NOT NULL,         -- prepare / compare / optimize / review / plan

    -- 状态
    status TEXT NOT NULL DEFAULT 'created',
    -- created → planning → running → blocked → verifying → completed → failed

    -- 计划与进度
    plan_json TEXT,                  -- TaskState.plan_steps 的 JSON
    current_step TEXT,
    completed_steps_json TEXT,
    pending_steps_json TEXT,

    -- 阻塞
    blockers_json TEXT,

    -- 下一步
    next_action TEXT,

    -- 验收
    acceptance_criteria_json TEXT,
    verification_results_json TEXT,

    -- 重规划
    replan_count INTEGER DEFAULT 0,

    -- 最终输出
    final_report TEXT,
    next_suggestions_json TEXT,

    -- 关联的任务 ID（agent_task 表）
    task_ids_json TEXT,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (user_id) REFERENCES user (id),
    FOREIGN KEY (session_id) REFERENCES copilot_session (id)
);
```

### 第 3 层：编排层 — 闭环状态机

**文件**: 新 `app/orchestration/` 模块（或改造 `app/agents/coordinator.py`）

```
                  ┌──────────┐
                  │  START   │
                  └────┬─────┘
                       ↓
                  ┌──────────┐
            ┌────→│ precheck │  检查前置条件（简历/岗位/知识库）
            │     └────┬─────┘
            │          ↓
            │     ┌──────────┐
            │     │ planner  │  生成 plan_steps + acceptance_criteria
            │     └────┬─────┘
            │          ↓
            │     ┌──────────┐
            │  ┌─→│ executor │  执行 plan_steps（逐 step 调 SubAgent）
            │  │  └────┬─────┘
            │  │       ↓
            │  │  ┌──────────┐
            │  │  │ verifier │  逐 step 验收，判断是否达标
            │  │  └────┬─────┘
            │  │       ↓
            │  │   all_verified?
            │  │    ├─ yes ──→ finalizer → END
            │  │    └─ no ──→ replan_count < max?
            │  │              ├─ yes → replanner → executor
            │  └──────────────┘              │
            │                                │
            └────────────────────────────────┘ (replanner 修改 plan → 回到 executor)
```

**状态机伪代码**:

```python
class ClosedLoopOrchestrator:
    """闭环编排器：precheck → plan → execute → verify → (replan) → finalize"""

    async def run(self, goal: str, task_state: TaskState, context: PipelineContext) -> TaskState:

        # 1. Precheck — 检查前置条件
        task_state = await self._precheck(goal, context)
        if task_state.is_blocked():
            return task_state  # 返回阻塞信息给用户

        # 2. Planner — 生成计划
        task_state = await self._plan(goal, context, task_state)

        # 3. Execute + Verify loop
        while task_state.pending_steps or task_state.current_step:
            # 3a. 取下一个 step
            step = self._next_step(task_state)
            if step is None:
                break

            # 3b. 执行
            task_state = await self._execute_step(step, context, task_state)

            # 3c. 验收
            task_state = await self._verify_step(step, context, task_state)

            # 3d. 判断：这一步过了吗？
            if not self._step_passed(step, task_state):
                if task_state.needs_replan():
                    task_state = await self._replan(task_state)
                else:
                    task_state.goal_status = "blocked"
                    break

        # 4. Finalizer
        if task_state.all_verified():
            task_state = await self._finalize(task_state)

        return task_state
```

### 第 4 层：验证层 — 能力 Verifier

**文件**: 新 `app/orchestration/verifiers.py`

```python
class BaseVerifier(ABC):
    """验收器基类"""

    @abstractmethod
    async def verify(self, step_result: dict, criteria: list[str], context) -> VerificationResult:
        ...

@dataclass
class VerificationResult:
    passed: bool
    score: float        # 0-100
    detail: str
    suggested_fix: str | None
```

四个具体 Verifier:

| Verifier | 检查内容 | 打分维度 |
|----------|---------|---------|
| `MatchVerifier` | 匹配分析结果是否有结构化分数、明确短板、可行建议 | 完整性 40% + 具体性 30% + 可操作性 30% |
| `ResumeVerifier` | 优化建议是否覆盖分析中发现的短板、是否有具体修改方案 | 覆盖度 50% + 可执行性 50% |
| `InterviewVerifier` | 面试题是否覆盖 JD 要求的技术栈、是否针对简历短板、是否有难度分层 | 覆盖面 40% + 针对性 30% + 难度梯度 30% |
| `RecommendVerifier` | 推荐理由是否足够明确、分数是否有区分度、是否覆盖用户偏好 | 理由充分性 40% + 区分度 30% + 个性化 30% |

每个 Verifier 用 **fast 模型**（低成本）做结构化判断，输出 `VerificationResult`。

### 第 5 层：功能层 — Agent-native 任务

不再堆单点工具，而是补闭环强耦合的功能：

| 功能 | 用户输入 | Agent 闭环链路 | 用到哪些层 |
|------|---------|---------------|-----------|
| **岗位备战任务包** | "备战这个后端岗位" | precheck(简历+JD) → plan → match → verify → (optional: optimize → verify) → interview → verify → finalize | 全部 |
| **岗位对比决策** | "帮我对比这 3 个岗位" | precheck → plan → parallel match×3 → compare → recommend → verify → finalize | 全部 |
| **简历多版本迭代** | "优化我的简历到 80 分以上" | precheck → plan → loop(analyze → optimize → rescore → verify, until score≥80 or max_replan) → finalize | 1/2/3/4 |
| **面试复盘与补强** | "复盘昨天的面试，告诉我怎么补" | precheck(面试反馈) → plan → gap_analysis → learn_plan → verify → finalize | 全部 |
| **7/14 天行动计划** | "给我接下来两周的学习计划" | precheck(短板汇总) → plan → schedule × days → resource_match → verify → finalize | 全部 |

---

## 实施优先级

### 第一步：打基础（状态 + 数据库）
1. 新增 `TaskState` 数据类到 `app/copilot/state.py`
2. 新增 `agent_run` 表到 `database.py` + `crud.py`
3. 新增 `agent_run` API（CRUD 端点）

### 第二步：闭环编排
1. 新建 `app/orchestration/` 模块
2. 实现 `ClosedLoopOrchestrator`（precheck/planner/executor/verifier/replanner/finalizer）
3. Planner 用 primary 模型生成 `plan_steps` + `acceptance_criteria`

### 第三步：验收层
1. 实现 `BaseVerifier` + 4 个具体 Verifier
2. 集成到 orchestrator 的 verify 阶段
3. 全部用 fast 模型，低成本

### 第四步：Agent-native 功能
1. 岗位备战任务包（验证完整闭环）
2. 岗位对比决策
3. 简历多版本迭代
4. 面试复盘与补强
5. 7/14 天行动计划

---

## 与现有代码的共存策略

- `PipelineState` / `PipelineContext` **保留不动** — 它们仍然是单次 pipeline 执行的上下文
- 新增 `TaskState` — 是高一层级的任务推进状态
- Coordinator 的 ReAct graph **保留** — 它是"模糊意图 → 分发子 Agent"的 fallback 路径
- `ClosedLoopOrchestrator` 是**新路径** — 当用户目标明确匹配"agent-native 功能"时走闭环
- 路由优先级：Skill 命中 → 闭环编排（新）→ Coordinator ReAct（旧 fallback）
