<script setup>
import { inject, nextTick, onMounted, reactive, ref, watch } from "vue";
import { COPILOT_REPORT_MARKER } from "../shared/constants.js";
import { renderMarkdown } from "../shared/markdown.js";

const api = inject("api");
const setMessage = inject("setMessage");
const currentResume = inject("currentResume");
const currentJob = inject("currentJob");
const fetchTasks = inject("fetchTasks");
const currentUser = inject("currentUser");
const currentSessionId = inject("currentSessionId");
const loadSessions = inject("loadSessions");
const storeSessionId = inject("storeSessionId");
const switchView = inject("switchView");

const toolMetaMap = ref({});
const resumeGenKeywords = ref([]);

const messages = ref([]);
const input = ref("");
const running = ref(false);
const cancelFn = ref(null);
const container = ref(null);
const bottomAnchor = ref(null);

function waitForPaint() {
  return new Promise((resolve) => requestAnimationFrame(resolve));
}

async function scrollToBottom() {
  await nextTick();
  await waitForPaint();
  await waitForPaint();

  const el = container.value;
  if (!el) return;

  bottomAnchor.value?.scrollIntoView({ block: "end" });
  el.scrollTop = el.scrollHeight;
}

async function loadMeta() {
  try {
    const [tools, skills] = await Promise.all([
      api.copilotApi.listTools(),
      api.copilotApi.listSkills(),
    ]);
    const map = {};
    for (const tool of tools) map[tool.name] = tool;
    toolMetaMap.value = map;

    const resumeSkill = skills.find((skill) => skill.name === "定制简历");
    if (resumeSkill?.keywords) {
      resumeGenKeywords.value = resumeSkill.keywords;
    }
  } catch {
    // silent degrade
  }
}

function convertHistoryToMessages(historyMsgs) {
  const result = [];
  for (const msg of historyMsgs) {
    if (msg.role === "user" || msg.role === "human") {
      result.push({ role: "user", text: msg.content || "" });
      continue;
    }

    if (msg.role === "copilot" || msg.role === "assistant") {
      const content = (msg.content || "").trim();
      // 跳过空消息和残留的 tool_call JSON
      if (!content || content.startsWith('{"index"')) continue;
      if (content.startsWith(COPILOT_REPORT_MARKER)) {
        try {
          const report = JSON.parse(content.slice(COPILOT_REPORT_MARKER.length));
          const copilotMsg = reactive({
            role: "copilot",
            steps: [],
            final: report,
            error: null,
            _collapsed: false,
            _streamText: {},
          });

          for (const rawStep of report.steps || []) {
            copilotMsg.steps.push({
              tool: rawStep.tool,
              status: "done",
              summary: rawStep,
            });

            for (const key of ["analysis_text", "optimization_text", "questions_text", "generated_resume"]) {
              if (rawStep[key]) {
                copilotMsg._streamText[rawStep.tool] =
                  (copilotMsg._streamText[rawStep.tool] || "") + rawStep[key];
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

async function loadSessionHistory(sessionId) {
  try {
    const msgs = await api.copilotApi.getSessionMessages(sessionId);
    messages.value = msgs?.length ? convertHistoryToMessages(msgs) : [];
    await scrollToBottom();
  } catch {
    // session may have been deleted
  }
}

function addMessage(msg) {
  messages.value.push(msg);
}

function welcome(username) {
  if (messages.value.length > 0) return;

  addMessage({
    role: "copilot",
    text: `你好 ${username || ""}！我是 JobAgent AI 求职助手。\n\n我可以帮你：\n- 上传简历 -> 点击左侧“简历管理”\n- 新建岗位 -> 点击左侧“岗位管理”\n- 一键备战 -> 选中简历和岗位后，输入“全面备战”\n- 定制简历 -> 输入“帮我生成一份简历”\n- 岗位推荐 -> 点击左侧“岗位推荐”\n- 查看历史任务 -> 点击左侧“任务记录”\n\n在左侧选好简历和岗位后，直接对我说你的需求就行。`,
  });
}

async function resetForNewChat(username) {
  messages.value = [];
  welcome(username);
  await scrollToBottom();
}

function isResumeGenIntent(text) {
  const normalized = text.toLowerCase();
  return resumeGenKeywords.value.some((keyword) => normalized.includes(keyword));
}

function send() {
  const text = input.value.trim();
  if (!text || running.value) return;

  if (!currentJob.id) {
    setMessage("请先在左侧“岗位管理”中选择目标岗位。", true);
    return;
  }

  const isGenResume = isResumeGenIntent(text);
  if (!isGenResume && !currentResume.id) {
    setMessage("请先在左侧“简历管理”中选择当前简历，或输入“生成简历”类指令以使用自由文本模式。", true);
    return;
  }

  if (isGenResume && !currentResume.id && text.length < 20) {
    setMessage("请在指令后补充你的个人信息，例如技能、经历、项目和学历等。", true);
    return;
  }

  addMessage({ role: "user", text });
  input.value = "";

  const copilotMsg = reactive({
    role: "copilot",
    steps: [],
    final: null,
    error: null,
    _collapsed: false,
    _streamText: {},
  });
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

  if (currentSessionId.value) {
    payload.session_id = currentSessionId.value;
  }

  cancelFn.value = api.copilotApi.streamRun(payload, {
    onSessionCreated(sessionId) {
      if (sessionId && sessionId !== currentSessionId.value) {
        storeSessionId(sessionId);
      }
    },
    onStepStart(data) {
      const shortNames = {
        resume_agent: "简历分析与优化",
        interview_agent: "面试题生成",
        search_agent: "岗位推荐",
      };
      const label = shortNames[data.tool] || toolMetaMap.value[data.tool]?.description || data.tool;
      copilotMsg.steps.push({ tool: data.tool, label, status: "running", summary: null, error: null });
    },
    onStepProgress(data) {
      const step = copilotMsg.steps.find((item) => item.tool === data.agent && item.status === "running");
      if (step) {
        step.label = `${step.label.split(" - ")[0]} - ${data.state_summary || "..."}`;
      }
    },
    onStepComplete(data) {
      const step = copilotMsg.steps.find((item) => item.tool === data.tool && item.status === "running");
      if (step) {
        step.status = "done";
        step.summary = data.result;
      }
    },
    onStepError(data) {
      const step = copilotMsg.steps.find((item) => item.tool === data.tool && item.status === "running");
      if (step) {
        step.status = "error";
        step.error = data.error;
      }
      copilotMsg.error = data.error;
    },
    onStepToken(data) {
      const key = data.agent;
      if (!copilotMsg._streamText[key]) copilotMsg._streamText[key] = "";
      copilotMsg._streamText[key] += data.token;
    },
    onFinal(data) {
      copilotMsg.final = data;
      if (data.session_id && data.session_id !== currentSessionId.value) {
        storeSessionId(data.session_id);
      }
      running.value = false;
      Promise.all([fetchTasks(), loadSessions()]);
    },
    onError(err) {
      copilotMsg.error = typeof err === "string" ? err : JSON.stringify(err);
      running.value = false;
    },
  });
}

function cancel() {
  if (cancelFn.value) {
    cancelFn.value();
    cancelFn.value = null;
  }
  running.value = false;
}

watch(
  messages,
  () => {
    void scrollToBottom();
  },
  { deep: true, flush: "post" }
);

watch(
  running,
  () => {
    void scrollToBottom();
  },
  { flush: "post" }
);

onMounted(async () => {
  await loadMeta();
  if (currentSessionId.value) {
    await loadSessionHistory(currentSessionId.value);
  }
  if (messages.value.length === 0) {
    welcome(currentUser?.username || "");
    await scrollToBottom();
  }
});

defineExpose({ welcome, send, loadSessionHistory, resetForNewChat, scrollToBottom });
</script>

<template>
  <div class="chat-area">
    <div ref="container" class="chat-messages">
      <div v-for="(msg, idx) in messages" :key="idx" class="msg-wrapper" :class="msg.role">
        <div v-if="msg.role === 'user'" class="msg-bubble user-bubble">{{ msg.text }}</div>

        <div v-else-if="msg.text && !msg.steps" class="msg-bubble copilot-bubble">
          <div class="msg-text" v-html="msg.text.replace(/\n/g, '<br>')"></div>
        </div>

        <div v-else-if="msg.steps" class="msg-card">
          <div v-for="step in msg.steps" :key="step.tool" class="step-block" :class="'step-' + step.status">
            <div class="step-row">
              <span class="step-icon">{{ step.status === "running" ? "⏳" : step.status === "done" ? "✓" : "✗" }}</span>
              <span class="step-label">{{ step.status === "running" ? step.label : "" }}</span>
            </div>

            <div
              v-if="msg._streamText[step.tool]"
              class="stream-text"
              :class="{ 'stream-done': step.status === 'done' }"
              v-html="renderMarkdown(msg._streamText[step.tool]) + (step.status === 'running' ? '<span class=&quot;cursor-blink&quot;>▋</span>' : '')"
            ></div>
          </div>

          <div v-if="msg.final" class="msg-final"><p>{{ msg.final.summary }}</p></div>
          <div v-if="msg.error" class="msg-error">{{ msg.error }}</div>
        </div>
      </div>

      <div v-if="running" class="msg-wrapper copilot">
        <div class="msg-bubble copilot-bubble typing">处理中<span class="dots"></span></div>
      </div>

      <div ref="bottomAnchor" aria-hidden="true"></div>
    </div>

    <div class="chat-input-bar">
      <div class="quick-actions">
        <button class="btn btn-ghost btn-small" @click="switchView('resume')">📄 简历管理</button>
        <button class="btn btn-ghost btn-small" @click="switchView('job')">💼 新建岗位</button>
        <button
          class="btn btn-ghost btn-small"
          :disabled="running || !currentResume.id || !currentJob.id"
          @click="input='全面备战'; send()"
        >
          🎯 一键备战
        </button>
      </div>

      <div class="input-row">
        <input
          v-model="input"
          type="text"
          class="chat-input"
          placeholder="输入你的需求，例如：帮我全面备战这个岗位"
          :disabled="running"
          @keyup.enter="send"
        />
        <button class="btn btn-primary" :disabled="running || !input.trim()" @click="send">发送</button>
        <button v-if="running" class="btn btn-secondary" @click="cancel">取消</button>
      </div>
    </div>
  </div>
</template>
