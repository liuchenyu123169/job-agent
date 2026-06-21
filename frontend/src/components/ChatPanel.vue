<script setup>
import { inject, ref, reactive, nextTick, onMounted } from "vue";
import { COPILOT_REPORT_MARKER } from "./utils.js";

const api = inject("api");
const setMessage = inject("setMessage");
const currentResume = inject("currentResume");
const currentJob = inject("currentJob");
const fetchTasks = inject("fetchTasks");
const currentUser = inject("currentUser");

// 会话管理（状态由 App.vue 持有，ChatPanel 只消费）
const currentSessionId = inject("currentSessionId");
const sessions = inject("sessions");
const selectSession = inject("selectSession");
const newChat = inject("newChat");
const loadSessions = inject("loadSessions");
const storeSessionId = inject("storeSessionId");
const switchView = inject("switchView");

/* ── 工具元数据 ── */
const toolMetaMap = ref({});

async function loadMeta() {
  try {
    const [tools, skills] = await Promise.all([
      api.copilotApi.listTools(),
      api.copilotApi.listSkills(),
    ]);
    const map = {};
    for (const t of tools) map[t.name] = t;
    toolMetaMap.value = map;
    // 从后端动态获取「定制简历」关键词，消除前端硬编码重复
    const resumeSkill = skills.find(s => s.name === "定制简历");
    if (resumeSkill?.keywords) {
      resumeGenKeywords.value = resumeSkill.keywords;
    }
  } catch { /* 静默降级 */ }
}

/* ── 历史消息加载（由 App.vue 的 selectSession 调用） ── */
async function loadSessionHistory(sessionId) {
  try {
    const msgs = await api.copilotApi.getSessionMessages(sessionId);
    if (msgs && msgs.length > 0) {
      messages.value = convertHistoryToMessages(msgs);
    }
  } catch { /* 会话可能已删除 */ }
}

function convertHistoryToMessages(historyMsgs) {
  const result = [];
  for (const m of historyMsgs) {
    if (m.role === "user" || m.role === "human") {
      result.push({ role: "user", text: m.content || "" });
    } else if (m.role === "copilot" || m.role === "assistant") {
      const content = m.content || "";
      if (content.startsWith(COPILOT_REPORT_MARKER)) {
        try {
          const report = JSON.parse(content.slice(COPILOT_REPORT_MARKER.length));
          const copilotMsg = reactive({ role: "copilot", steps: [], final: report, error: null, _collapsed: false, _streamText: {} });
          for (const rawStep of report.steps || []) {
            const s = { tool: rawStep.tool, status: "done", summary: rawStep };
            copilotMsg.steps.push(s);
            // 恢复流式文本（新格式：text 字段）
            for (const key of ["analysis_text", "optimization_text", "questions_text", "generated_resume"]) {
              if (rawStep[key]) {
                copilotMsg._streamText[rawStep.tool] = (copilotMsg._streamText[rawStep.tool] || "") + rawStep[key];
              }
            }
          }
          result.push(copilotMsg);
        } catch {
          result.push({ role: "copilot", text: content.slice(COPILOT_REPORT_MARKER.length) });
        }
      } else {
        result.push({ role: "copilot", text: content });
      }
    }
  }
  return result;
}

/* ── 初始化 ── */
onMounted(async () => {
  loadMeta();
  if (currentSessionId.value) {
    await loadSessionHistory(currentSessionId.value);
  }
  if (messages.value.length === 0) {
    welcome(currentUser?.username || "");
  }
});

/* ── 聊天状态 ── */
const messages = ref([]);
const input = ref("");
const running = ref(false);
const cancelFn = ref(null);
const container = ref(null);

/* ── 步骤结果预处理 ── */
function preNormalize(step) {
  if (!step || !step.summary) return;
  Object.assign(step.summary, normalizeOutputFields(step.summary));
}

/* ── 简单 Markdown → HTML ── */
function _inline(s) {
  // 先处理行内代码 `xxx`（必须在加粗之前，避免 **`xx`** 冲突）
  s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
  // 加粗 **xxx**
  s = s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  return s;
}

function renderMarkdown(text) {
  if (!text) return "";
  // 预处理：确保 **标题**： 这类块级加粗标题前有换行
  text = text.replace(/([^\n])(\*\*[^*]+\*\*[：:])/g, "$1\n$2");

  const lines = text.split("\n");
  const out = [];
  let inUl = false, inOl = false;

  function closeLists() {
    if (inUl) { out.push("</ul>"); inUl = false; }
    if (inOl) { out.push("</ol>"); inOl = false; }
  }

  // 偷看后续非空行
  function peekNonEmpty(from) {
    for (let j = from; j < lines.length; j++) {
      if (lines[j].trim()) return lines[j].trim();
    }
    return null;
  }

  for (let i = 0; i < lines.length; i++) {
    const trimmed = lines[i].trim();

    // 空行
    if (!trimmed) {
      const next = peekNonEmpty(i + 1);
      // 有序列表：如果下个非空行还是数字开头，保持列表打开
      if (inOl && next && /^\d+[\.\)]\s/.test(next)) continue;
      // 无序列表：同理
      if (inUl && next && /^[\-\*]\s(?!\*)/.test(next)) continue;
      closeLists();
      continue;
    }

    // 标题 # / ## / ### / ####
    const headMatch = trimmed.match(/^(#{1,4})\s+(.+)/);
    if (headMatch) {
      closeLists();
      const level = Math.min(headMatch[1].length + 1, 5); // #→h2, ##→h3, ###→h4, ####→h5
      out.push("<h" + level + ">" + _inline(headMatch[2]) + "</h" + level + ">");
      continue;
    }

    // 无序列表
    const ulMatch = trimmed.match(/^[\-\*]\s(?!\*)(.+)/);
    if (ulMatch) {
      if (inOl) { out.push("</ol>"); inOl = false; }
      if (!inUl) { out.push("<ul>"); inUl = true; }
      out.push("<li>" + _inline(ulMatch[1]) + "</li>");
      continue;
    }

    // 有序列表
    const olMatch = trimmed.match(/^\d+[\.\)]\s+(.+)/);
    if (olMatch) {
      if (inUl) { out.push("</ul>"); inUl = false; }
      if (!inOl) { out.push("<ol>"); inOl = true; }
      out.push("<li>" + _inline(olMatch[1]) + "</li>");
      continue;
    }

    // 普通行
    closeLists();
    out.push("<p>" + _inline(trimmed) + "</p>");
  }
  closeLists();
  return out.join("");
}

/* ── 消息操作 ── */
function addMessage(msg) {
  messages.value.push(msg);
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
      text: `你好 ${username || ""}！我是 JobAgent AI 求职助手。\n\n我可以帮你：\n· 上传简历 → 点击左侧「简历管理」\n· 新建岗位 → 点击左侧「岗位管理」\n· 一键备战 → 选中简历和岗位后，输入「全面备战」\n· 定制简历 → 输入「帮我生成一份简历」\n· 岗位推荐 → 点击左侧「岗位推荐」\n· 查看历史任务 → 点击左侧「任务记录」\n\n在左侧选好简历和岗位后，直接对我说你的需求就行。`,
    });
  }
}

/* ── 简历生成意图检测（关键词从后端 Skill 动态获取，避免前端硬编码重复） ── */
const resumeGenKeywords = ref([]);

function isResumeGenIntent(text) {
  const t = text.toLowerCase();
  return resumeGenKeywords.value.some(kw => t.includes(kw));
}

/* ── 发送消息 ── */
function send() {
  const text = input.value.trim();
  if (!text || running.value) return;
  if (!currentJob.id) { setMessage("请先在左侧「岗位管理」中选择目标岗位。", true); return; }

  const isGenResume = isResumeGenIntent(text);
  if (!isGenResume && !currentResume.id) {
    setMessage("请先在左侧「简历管理」中选择当前简历，或输入「生成简历」类指令以使用自由文本模式。", true);
    return;
  }
  if (isGenResume && !currentResume.id && text.length < 20) {
    setMessage("请在指令后补充您的个人信息（技能/经历/项目/学历等），例如：\n「帮我生成一份简历。我精通Python和Django，有3年后端开发经验...」", true);
    return;
  }

  addMessage({ role: "user", text });
  input.value = "";

  const copilotMsg = reactive({ role: "copilot", steps: [], final: null, error: null, _collapsed: false, _streamText: {} });
  addMessage(copilotMsg);
  running.value = true;

  const payload = {
    goal: text,
    job_id: Number(currentJob.id),
  };
  if (currentResume.id) {
    payload.resume_id = Number(currentResume.id);
  } else if (isGenResume) {
    payload.personal_info = text;
  }
  // 多轮对话：带上当前会话 ID
  if (currentSessionId.value) {
    payload.session_id = currentSessionId.value;
  }

  cancelFn.value = api.copilotApi.streamRun(payload,
    {
      // 从 HTTP 响应头立即拿到 session_id，不等 final 事件
      onSessionCreated(sessionId) {
        if (sessionId && sessionId !== currentSessionId.value) {
          storeSessionId(sessionId);
        }
      },
      onStepStart(data) {
        const shortNames = { resume_agent: "简历分析与优化", interview_agent: "面试题生成", search_agent: "岗位推荐" };
        const label = shortNames[data.tool] || (toolMetaMap.value[data.tool] || {}).description || data.tool;
        copilotMsg.steps.push({ tool: data.tool, label, status: "running", summary: null, error: null });
      },
      onStepProgress(data) {
        const s = copilotMsg.steps.find(x => x.tool === data.agent && x.status === "running");
        if (s) s.label = `${s.label.split(" — ")[0]} — ${data.state_summary || '...'}`;
      },
      onStepComplete(data) {
        const s = copilotMsg.steps.find(x => x.tool === data.tool && x.status === "running");
        if (s) { s.status = "done"; s.summary = data.result; }
      },
      onStepError(data) {
        const s = copilotMsg.steps.find(x => x.tool === data.tool && x.status === "running");
        if (s) { s.status = "error"; s.error = data.error; }
        copilotMsg.error = data.error;
      },
      onStepToken(data) {
        const key = data.agent;
        if (!copilotMsg._streamText[key]) copilotMsg._streamText[key] = "";
        copilotMsg._streamText[key] += data.token;
      },
      onFinal(data) {
        copilotMsg.final = data;
        // 保存/更新会话 ID（首次对话时后端返回；重试时覆盖旧值）
        if (data.session_id && data.session_id !== currentSessionId.value) {
          storeSessionId(data.session_id);
        }
        running.value = false;
        Promise.all([fetchTasks(), loadSessions()]);  // 并行刷新任务列表 + 侧边栏
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

defineExpose({ messages, welcome, send, loadSessionHistory });
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
          <div v-for="step in msg.steps" :key="step.tool" class="step-block" :class="'step-' + step.status">
            <div class="step-row">
              <span class="step-icon">{{ step.status === 'running' ? '⏳' : step.status === 'done' ? '' : '❌' }}</span>
              <span class="step-label">{{ step.status === 'running' ? step.label : '' }}</span>
            </div>

            <!-- 流式文本（生成中 + 完成后统一由此显示） -->
            <div v-if="msg._streamText[step.tool]" class="stream-text" :class="{ 'stream-done': step.status === 'done' }" v-html="renderMarkdown(msg._streamText[step.tool]) + (step.status === 'running' ? '<span class=\'cursor-blink\'>▊</span>' : '')"></div>
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
        <button class="btn btn-ghost btn-small" @click="switchView('resume')">📄 简历管理</button>
        <button class="btn btn-ghost btn-small" @click="switchView('job')">💼 新建岗位</button>
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
