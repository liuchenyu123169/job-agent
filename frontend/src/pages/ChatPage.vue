<script setup>
import { inject, nextTick, onMounted, reactive, ref, watch } from "vue";
import { COPILOT_REPORT_MARKER } from "../shared/constants.js";
import { buildWelcomeText } from "../shared/copilotText.js";
import CopilotMessageCard from "../components/CopilotMessageCard.vue";
import ChatInputBar from "../components/ChatInputBar.vue";

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

const TOOL_SHORT_NAMES = {
  match_analyze: "匹配分析",
  optimize_resume: "简历优化",
  generate_interview_questions: "面试题生成",
  generate_resume: "定制简历生成",
  recommend_jobs: "岗位推荐",
  public_search: "公开搜索",
  fetch_job_page: "页面抓取",
  search_knowledge: "知识检索",
  list_resumes: "简历列表",
  list_jobs: "岗位列表",
};

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

            for (const key of [
              "analysis_text",
              "optimization_text",
              "questions_text",
              "generated_resume",
            ]) {
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
  addMessage({ role: "copilot", text: buildWelcomeText(username) });
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

function buildPayload(text) {
  const payload = { goal: text };
  if (currentJob.id) payload.job_id = Number(currentJob.id);
  if (currentResume.id) payload.resume_id = Number(currentResume.id);
  else if (isResumeGenIntent(text)) payload.personal_info = text;
  if (currentSessionId.value) payload.session_id = currentSessionId.value;
  return payload;
}

function send() {
  const text = input.value.trim();
  if (!text || running.value) return;

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

  const payload = buildPayload(text);

  cancelFn.value = api.copilotApi.streamRun(payload, {
    onSessionCreated(sessionId) {
      if (sessionId && sessionId !== currentSessionId.value) {
        storeSessionId(sessionId);
      }
    },
    onStepStart(data) {
      const label =
        TOOL_SHORT_NAMES[data.tool] || toolMetaMap.value[data.tool]?.description || data.tool;
      copilotMsg.steps.push({
        tool: data.tool,
        label,
        status: "running",
        summary: null,
        error: null,
      });
    },
    onStepProgress(data) {
      const step = copilotMsg.steps.find(
        (item) => item.tool === data.agent && item.status === "running"
      );
      if (step) {
        step.label = `${step.label.split(" - ")[0]} - ${data.state_summary || "..."}`;
      }
    },
    onStepComplete(data) {
      const step = copilotMsg.steps.find(
        (item) => item.tool === data.tool && item.status === "running"
      );
      if (step) {
        step.status = "done";
        step.summary = data.result;
      }
    },
    onStepError(data) {
      const step = copilotMsg.steps.find(
        (item) => item.tool === data.tool && item.status === "running"
      );
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
      copilotMsg._status = data.status || "COMPLETED";
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
      <CopilotMessageCard
        v-for="(msg, idx) in messages"
        :key="idx"
        :role="msg.role"
        :text="msg.text"
        :steps="msg.steps"
        :stream-text-map="msg._streamText"
        :final="msg.final"
        :error="msg.error"
        :status="msg._status"
      />

      <div v-if="running" class="msg-wrapper copilot">
        <div class="msg-bubble copilot-bubble typing">处理中<span class="dots"></span></div>
      </div>

      <div ref="bottomAnchor" aria-hidden="true"></div>
    </div>

    <ChatInputBar
      v-model="input"
      :running="running"
      :switch-view="switchView"
      @send="send"
      @cancel="cancel"
    />
  </div>
</template>
