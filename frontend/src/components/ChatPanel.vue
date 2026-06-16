<script setup>
import { inject, ref, nextTick } from "vue";
import { normalizeToArray } from "./utils.js";

const api = inject("api");
const setMessage = inject("setMessage");
const currentResume = inject("currentResume");
const currentJob = inject("currentJob");
const fetchTasks = inject("fetchTasks");

/* ── 工具元数据 + Skill 列表（从后端动态加载） ── */
const toolMetaMap = ref({});     // { name: { description, keywords, render_type } }
const skillList = ref([]);       // [{ name, description, keywords, mode, sub_agents, tools }]

async function loadMeta() {
  try {
    const [tools, skills] = await Promise.all([
      api.copilotApi.listTools(),
      api.copilotApi.listSkills(),
    ]);
    const map = {};
    for (const t of tools) map[t.name] = t;
    toolMetaMap.value = map;
    skillList.value = skills;
  } catch { /* 静默降级：用硬编码兜底 */ }
}

loadMeta();

/* ── 聊天状态 ── */
const messages = ref([]);       // {role, text?, steps?, final?, error?}
const input = ref("");
const running = ref(false);
const cancelFn = ref(null);
const container = ref(null);

/* ── 步骤结果预处理：规范化所有数组字段 ── */
function preNormalize(step) {
  if (!step || !step.summary) return;
  const s = step.summary;
  // 匹配分析中的 list 字段
  ["advantages", "weaknesses", "suggestions"].forEach(k => {
    if (s.analysis && s.analysis[k] !== undefined) s.analysis[k] = normalizeToArray(s.analysis[k]);
  });
  // 简历优化中的 list 字段
  if (s.optimization) {
    ["skill_keywords", "project_suggestions", "resume_rewrite_suggestions", "risk_points"].forEach(k => {
      if (s.optimization[k] !== undefined) s.optimization[k] = normalizeToArray(s.optimization[k]);
    });
  }
  // 面试题分组
  if (s.questions) {
    ["technical_questions", "project_questions", "behavior_questions", "risk_questions"].forEach(k => {
      if (s.questions[k] !== undefined) s.questions[k] = normalizeToArray(s.questions[k]);
    });
  }
}

/* ── 消息操作 ── */
function addMessage(msg) {
  messages.value.push(msg);
  // 消息在列表末尾之后才触发滚动
  nextTick(() => {
    if (container.value) {
      container.value.scrollTop = container.value.scrollHeight;
    }
  });
}

function welcome(username) {
  if (messages.value.length === 0) {
    addMessage({
      role: "copilot",
      text: `你好 ${username || ""}！我是 JobAgent AI 求职助手。\n\n我可以帮你：\n· 上传简历 → 点击左侧「简历管理」\n· 新建岗位 → 点击左侧「岗位管理」\n· 一键备战 → 选中简历和岗位后，输入「全面备战」\n· 岗位推荐 → 点击左侧「岗位推荐」\n· 查看历史任务 → 点击左侧「任务记录」\n\n在左侧选好简历和岗位后，直接对我说你的需求就行。`,
    });
  }
}

/* ── 意图解析 → Skill 匹配（优先后端 Skills，兜底硬编码工具关键词） ── */
function resolveIntent(text) {
  const t = text.toLowerCase();
  // 1. 匹配所有 Skill（支持多意图），合并 sub_agents 去重
  if (skillList.value.length > 0) {
    const matched = [];
    for (const skill of skillList.value) {
      const score = (skill.keywords || []).filter(k => t.includes(k)).length;
      if (score > 0) matched.push({ score, skill });
    }
    if (matched.length > 0) {
      matched.sort((a, b) => b.score - a.score);
      // 合并所有 matched skill 的 sub_agents，去重保序
      const agents = [];
      const seen = new Set();
      for (const { skill } of matched) {
        for (const name of (skill.sub_agents || [])) {
          if (!seen.has(name)) { seen.add(name); agents.push(name); }
        }
      }
      return { mode: "coordinator", tools: null, sub_agents: agents };
    }
  }
  // 2. 兜底：用工具关键词匹配（fast 模式）
  const meta = toolMetaMap.value;
  const entries = Object.entries(meta);
  if (entries.length > 0) {
    const matched = [];
    for (const [name, info] of entries) {
      if ((info.keywords || []).some(k => t.includes(k))) matched.push(name);
    }
    if (matched.length > 0) return { mode: "fast", tools: matched, sub_agents: null };
  }
  // 3. 最终兜底：Coordinator 全跑
  return { mode: "coordinator", tools: null, sub_agents: ["resume_agent", "interview_agent"] };
}

/* ── 发送消息 ── */
function send() {
  const text = input.value.trim();
  if (!text || running.value) return;
  if (!currentResume.id) { setMessage("请先在左侧「简历管理」中选择当前简历。", true); return; }
  if (!currentJob.id) { setMessage("请先在左侧「岗位管理」中选择当前岗位。", true); return; }

  addMessage({ role: "user", text });
  input.value = "";

  const intent = resolveIntent(text);
  const copilotMsg = { role: "copilot", steps: [], final: null, error: null };
  addMessage(copilotMsg);
  running.value = true;

  cancelFn.value = api.copilotApi.streamRun(
    {
      goal: text,
      resume_id: Number(currentResume.id),
      job_id: Number(currentJob.id),
      mode: intent.mode,
      tools: intent.tools,
    },
    {
      onStepStart(data) {
        const label = (toolMetaMap.value[data.tool] || {}).description || data.tool;
        copilotMsg.steps.push({ tool: data.tool, label, status: "running", summary: null, error: null });
      },
      onStepComplete(data) {
        const s = copilotMsg.steps.find(x => x.tool === data.tool && x.status === "running");
        if (s) { s.status = "done"; s.summary = data.result; preNormalize(s); }
      },
      onStepError(data) {
        const s = copilotMsg.steps.find(x => x.tool === data.tool && x.status === "running");
        if (s) { s.status = "error"; s.error = data.error; }
        copilotMsg.error = data.error;
      },
      onFinal(data) {
        copilotMsg.final = data;
        running.value = false;
        fetchTasks();
      },
      onError(err) {
        copilotMsg.error = typeof err === "string" ? err : JSON.stringify(err);
        running.value = false;
      },
    }
  );
}

function cancel() {
  if (cancelFn.value) { cancelFn.value(); cancelFn.value = null; }
  running.value = false;
}

defineExpose({ messages, welcome, send });
</script>

<template>
  <div class="chat-area">
    <div class="chat-messages" ref="container">
      <div v-for="(msg, idx) in messages" :key="idx" class="msg-wrapper" :class="msg.role">
        <!-- 用户消息 -->
        <div v-if="msg.role === 'user'" class="msg-bubble user-bubble">{{ msg.text }}</div>

        <!-- Copilot 文本消息 -->
        <div v-else-if="msg.text && !msg.steps" class="msg-bubble copilot-bubble">
          <div class="msg-text" v-html="msg.text.replace(/\n/g, '<br>')"></div>
        </div>

        <!-- Copilot 步骤消息 -->
        <div v-else-if="msg.steps" class="msg-card">
          <div class="msg-card-title">
            <span v-if="!msg.final && !msg.error">🤖 执行中...</span>
            <span v-else-if="msg.error">❌ 执行出错</span>
            <span v-else>✅ 执行完毕</span>
          </div>
          <div v-for="step in msg.steps" :key="step.tool" class="step-block" :class="'step-' + step.status">
            <div class="step-row">
              <span class="step-icon">{{ step.status === 'running' ? '⏳' : step.status === 'done' ? '✅' : '❌' }}</span>
              <span class="step-label">{{ step.label }}</span>
            </div>

            <!-- 匹配分析 / 简历优化 结果 -->
            <div v-if="step.status === 'done' && step.summary?.analysis" class="step-detail">
              <div v-if="step.summary.analysis.match_score !== undefined" class="match-score-big">
                {{ step.summary.analysis.match_score }}<span>分</span>
              </div>
              <div v-if="step.summary.analysis.match_reason" class="detail-item">
                <p>{{ step.summary.analysis.match_reason }}</p>
              </div>
              <div v-if="step.summary.analysis.advantages?.length" class="detail-item">
                <h6>优势</h6>
                <ul><li v-for="a in step.summary.analysis.advantages" :key="a">{{ a }}</li></ul>
              </div>
              <div v-if="step.summary.analysis.weaknesses?.length" class="detail-item">
                <h6>不足</h6>
                <ul><li v-for="w in step.summary.analysis.weaknesses" :key="w">{{ w }}</li></ul>
              </div>
              <div v-if="step.summary.analysis.suggestions?.length" class="detail-item">
                <h6>建议</h6>
                <ul><li v-for="s in step.summary.analysis.suggestions" :key="s">{{ s }}</li></ul>
              </div>
            </div>

            <div v-if="step.status === 'done' && step.summary?.optimization" class="step-detail">
              <p v-if="step.summary.optimization.summary" class="detail-text">{{ step.summary.optimization.summary }}</p>
              <div v-if="step.summary.optimization.skill_keywords?.length" class="detail-item">
                <h6>技能关键词</h6>
                <div class="tag-list"><span v-for="k in step.summary.optimization.skill_keywords" :key="k" class="tag">{{ k }}</span></div>
              </div>
              <div v-if="step.summary.optimization.project_suggestions?.length" class="detail-item">
                <h6>项目建议</h6>
                <ul><li v-for="p in step.summary.optimization.project_suggestions" :key="p">{{ p }}</li></ul>
              </div>
              <div v-if="step.summary.optimization.resume_rewrite_suggestions?.length" class="detail-item">
                <h6>改写建议</h6>
                <ul><li v-for="r in step.summary.optimization.resume_rewrite_suggestions" :key="r">{{ r }}</li></ul>
              </div>
              <div v-if="step.summary.optimization.risk_points?.length" class="detail-item">
                <h6>风险点</h6>
                <ul><li v-for="r in step.summary.optimization.risk_points" :key="r">{{ r }}</li></ul>
              </div>
            </div>

            <!-- 面试题结果 -->
            <div v-if="step.status === 'done' && step.summary?.questions" class="step-detail">
              <template v-for="group in [
                {key:'technical_questions',label:'技术问题'},
                {key:'project_questions',label:'项目问题'},
                {key:'behavior_questions',label:'行为问题'},
                {key:'risk_questions',label:'风险问题'}
              ]" :key="group.key">
                <div v-if="step.summary.questions[group.key]?.length" class="detail-item">
                  <h6>{{ group.label }}（{{ step.summary.questions[group.key].length }}）</h6>
                  <div v-for="(q, qi) in step.summary.questions[group.key]" :key="qi" class="question-item">
                    <strong>{{ qi + 1 }}. {{ q.question || q.title || q }}</strong>
                    <small v-if="q.why_ask"><em>为什么问：</em>{{ q.why_ask }}</small>
                    <small v-if="q.answer_hint"><em>回答提示：</em>{{ q.answer_hint }}</small>
                  </div>
                </div>
              </template>
            </div>
          </div>
          <div v-if="msg.final" class="msg-final"><p>{{ msg.final.summary }}</p></div>
          <div v-if="msg.error" class="msg-error">{{ msg.error }}</div>
        </div>
      </div>
      <!-- 执行中指示器 -->
      <div v-if="running" class="msg-wrapper copilot">
        <div class="msg-bubble copilot-bubble typing">处理中<span class="dots"></span></div>
      </div>
    </div>

    <!-- 输入区 -->
    <div class="chat-input-bar">
      <div class="quick-actions">
        <button class="btn btn-ghost btn-small" @click="$emit('openPanel', 'resume')">📄 简历管理</button>
        <button class="btn btn-ghost btn-small" @click="$emit('openPanel', 'job')">💼 新建岗位</button>
        <button class="btn btn-ghost btn-small" :disabled="running || !currentResume.id || !currentJob.id" @click="input='全面备战'; send()">🚀 一键备战</button>
      </div>
      <div class="input-row">
        <input v-model="input" type="text" class="chat-input"
          placeholder="输入你的需求，如「帮我全面备战这个岗位」"
          :disabled="running"
          @keyup.enter="send" />
        <button class="btn btn-primary" :disabled="running || !input.trim()" @click="send">发送</button>
        <button v-if="running" class="btn btn-secondary" @click="cancel">取消</button>
      </div>
    </div>
  </div>
</template>
