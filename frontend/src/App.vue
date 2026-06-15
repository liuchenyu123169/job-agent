<script setup>
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from "vue";
import axios from "axios";
import {
  agentApi,
  authApi,
  copilotApi,
  jobApi,
  knowledgeApi,
  resumeApi,
  setUnauthorizedHandler,
  taskApi
} from "./api";

/* ── 侧边栏入口 ── */
const sidebarItems = [
  { key: "chat",     label: "对话",     icon: "💬" },
  { key: "resume",   label: "简历管理", icon: "📄" },
  { key: "job",      label: "岗位管理", icon: "💼" },
  { key: "recommend",label: "岗位推荐", icon: "🔍" },
  { key: "task",     label: "任务记录", icon: "📋" },
  { key: "knowledge",label: "RAG 知识库",icon: "⚙️" },
];

const activePanel = ref(null); // null | 'resume' | 'job' | 'recommend' | 'task' | 'knowledge'

/* ── 认证 ── */
const token = ref(localStorage.getItem("token") || "");
const currentUser = ref(null);
const message = ref("");
const error = ref("");
const authMode = ref("login");
const authForm = reactive({ username: "", password: "" });
const isLoggedIn = computed(() => Boolean(token.value && currentUser.value));

/* ── 当前选中的简历/岗位 ── */
const currentResume = reactive({ id: null, localId: null, fileName: "", contentPreview: "", content: "" });
const currentJob = reactive({ id: null, localId: null, company: "", title: "", jdText: "" });

/* ── 加载状态 ── */
const loadingMap = reactive({
  auth: false, restore: false,
  resumeUpload: false, resumeList: false, resumeDetail: false,
  jobCreate: false, jobList: false, jobDetail: false,
  knowledgeBuild: false, knowledgeSearch: false,
  recommend: false, tasks: false, taskDetail: false,
});

/* ── 各面板状态 ── */
const resumeState = reactive({ selectedFile: null, list: [], detailInput: "", detailResult: null });
const jobState = reactive({ form: { company: "", title: "", jd_text: "" }, list: [], detailInput: "", detailResult: null });
const knowledgeState = reactive({ buildResult: null, searchQuery: "", topK: 5, searchResult: null });
const recommendState = reactive({ topK: 5, maxJobs: 10, result: null });
const taskState = reactive({ filterTaskType: "", items: [], selectedTask: null });

/* ── 对话 ── */
const chatMessages = ref([]);       // {role, text?, steps?, final?, error?}
const chatInput = ref("");
const chatRunning = ref(false);
const chatCancelFn = ref(null);
const chatContainer = ref(null);

const COPILOT_TOOL_LABELS = {
  match_analyze: "匹配分析",
  optimize_resume: "简历优化",
  generate_interview_questions: "面试题生成",
};

function addChatMessage(msg) {
  chatMessages.value.push(msg);
  nextTick(() => {
    if (chatContainer.value) {
      chatContainer.value.scrollTop = chatContainer.value.scrollHeight;
    }
  });
}

function welcomeMessage() {
  if (chatMessages.value.length === 0) {
    addChatMessage({
      role: "copilot",
      text: `你好 ${currentUser.value?.username || ""}！我是 JobAgent AI 求职助手。\n\n我可以帮你：\n· 上传简历 → 点击左侧「简历管理」\n· 新建岗位 → 点击左侧「岗位管理」\n· 一键备战 → 选中简历和岗位后，输入「全面备战」\n· 岗位推荐 → 点击左侧「岗位推荐」\n· 查看历史任务 → 点击左侧「任务记录」\n\n在左侧选好简历和岗位后，直接对我说你的需求就行。`,
    });
  }
}

/* ── 工具函数 ── */
function setMessage(text, isError = false) {
  if (isError) { error.value = text; message.value = ""; }
  else { message.value = text; error.value = ""; }
}
function getErrorMessage(err) {
  if (axios.isAxiosError(err)) return err.response?.data?.detail || err.message || "请求失败";
  return err?.message || "请求失败";
}
function setLoading(key, value) { loadingMap[key] = value; }
function normalizeToArray(value) {
  if (Array.isArray(value)) return value.filter(Boolean);
  if (typeof value === "string" && value.trim()) return [value.trim()];
  return [];
}
function formatJson(value) {
  if (value === undefined || value === null || value === "") return "暂无内容";
  try { return JSON.stringify(value, null, 2); } catch { return String(value); }
}
function findFirstValue(source, keys) {
  if (!source || typeof source !== "object") return null;
  for (const key of keys) { const v = source[key]; if (v !== undefined && v !== null && v !== "") return v; }
  return null;
}
function getMatchScore(source) {
  const raw = findFirstValue(source, ["match_score", "score"]);
  if (raw === null) return 0;
  const matched = String(raw).match(/\d+/);
  const score = matched ? Number(matched[0]) : Number(raw);
  return Number.isNaN(score) ? 0 : Math.max(0, Math.min(100, score));
}

function ensureResumeAndJob() {
  if (!currentResume.id) { setMessage("请先在左侧「简历管理」中选择当前简历。", true); return false; }
  if (!currentJob.id) { setMessage("请先在左侧「岗位管理」中选择当前岗位。", true); return false; }
  return true;
}

/* ── 简历/岗位选择 ── */
function applyResumeSelection(resume) {
  if (!resume) return;
  currentResume.id = resume.id ?? resume.resume_id ?? null;
  currentResume.localId = resume.local_resume_id ?? null;
  currentResume.fileName = resume.file_name || "";
  currentResume.contentPreview = resume.content_preview || String(resume.content || "").slice(0, 200);
  currentResume.content = resume.content || "";
  setMessage(`已选中第 ${currentResume.localId} 份简历。`);
}
function applyJobSelection(job) {
  if (!job) return;
  currentJob.id = job.id ?? job.job_id ?? null;
  currentJob.localId = job.local_job_id ?? null;
  currentJob.company = job.company || "";
  currentJob.title = job.title || "";
  currentJob.jdText = job.jd_text || job.jd_preview || "";
  setMessage(`已选中第 ${currentJob.localId} 个岗位。`);
}
function resetCurrentResume() {
  currentResume.id = null; currentResume.localId = null; currentResume.fileName = "";
  currentResume.contentPreview = ""; currentResume.content = "";
}
function resetCurrentJob() {
  currentJob.id = null; currentJob.localId = null; currentJob.company = "";
  currentJob.title = ""; currentJob.jdText = "";
}

/* ── 认证 ── */
function clearSession(notify = true) {
  localStorage.removeItem("token");
  token.value = ""; currentUser.value = null;
  resetCurrentResume(); resetCurrentJob();
  chatMessages.value = [];
  if (notify) setMessage("登录状态已失效，请重新登录。", true);
}
async function restoreSession() {
  if (!token.value) return;
  setLoading("restore", true);
  try {
    const user = await authApi.getCurrentUser();
    currentUser.value = user;
    welcomeMessage();
    await Promise.all([fetchResumeList(), fetchJobList(), fetchTasks()]);
  } catch (err) { clearSession(false); setMessage(getErrorMessage(err), true); }
  finally { setLoading("restore", false); }
}
async function submitAuth() {
  if (!authForm.username || !authForm.password) { setMessage("请输入用户名和密码。", true); return; }
  setLoading("auth", true);
  try {
    const resp = authMode.value === "register"
      ? await authApi.register(authForm.username, authForm.password)
      : await authApi.login(authForm.username, authForm.password);
    token.value = resp.access_token;
    localStorage.setItem("token", resp.access_token);
    currentUser.value = { id: resp.user_id, username: resp.username };
    authForm.username = ""; authForm.password = "";
    welcomeMessage();
    await Promise.all([fetchResumeList(), fetchJobList(), fetchTasks()]);
  } catch (err) { setMessage(getErrorMessage(err), true); }
  finally { setLoading("auth", false); }
}
function logout() { clearSession(false); setMessage("已退出登录。"); }

/* ── 面板操作 ── */
function togglePanel(key) {
  activePanel.value = activePanel.value === key ? null : key;
}
function closePanel() { activePanel.value = null; }

/* ── API 调用（复用于面板和对话） ── */
async function fetchResumeList() {
  if (!isLoggedIn.value) return;
  setLoading("resumeList", true);
  try { resumeState.list = (await resumeApi.listResumes()).items || []; }
  catch (err) { setMessage(getErrorMessage(err), true); }
  finally { setLoading("resumeList", false); }
}
async function fetchJobList() {
  if (!isLoggedIn.value) return;
  setLoading("jobList", true);
  try { jobState.list = (await jobApi.listJobs()).items || []; }
  catch (err) { setMessage(getErrorMessage(err), true); }
  finally { setLoading("jobList", false); }
}
async function fetchTasks() {
  if (!isLoggedIn.value) return;
  setLoading("tasks", true);
  try {
    const params = {}; if (taskState.filterTaskType.trim()) params.task_type = taskState.filterTaskType.trim();
    taskState.items = (await taskApi.listTasks(params)).items || [];
  } catch (err) { setMessage(getErrorMessage(err), true); }
  finally { setLoading("tasks", false); }
}
async function fetchTaskDetail(taskId) {
  setLoading("taskDetail", true);
  taskState.selectedTask = null; // 先清空触发重新渲染
  try {
    const task = await taskApi.getTask(taskId);
    taskState.selectedTask = task;
    setMessage(`已加载任务 #${taskId}`);
  } catch (err) { setMessage(getErrorMessage(err), true); }
  finally { setLoading("taskDetail", false); }
}

function onResumeFileChange(event) { resumeState.selectedFile = (event.target.files || [])[0] || null; }

async function uploadResume() {
  if (!resumeState.selectedFile) { setMessage("请先选择文件。", true); return; }
  setLoading("resumeUpload", true);
  try {
    const resp = await resumeApi.uploadResume(resumeState.selectedFile);
    applyResumeSelection({ id: resp.resume_id, local_resume_id: resp.local_resume_id, file_name: resp.file_name, content_preview: resp.content_preview });
    await fetchResumeList();
  } catch (err) { setMessage(getErrorMessage(err), true); }
  finally { setLoading("resumeUpload", false); }
}
async function fetchResumeDetail() {
  if (!resumeState.detailInput) { setMessage("请输入本地简历编号。", true); return; }
  setLoading("resumeDetail", true);
  try {
    const resp = await resumeApi.getResumeByLocalId(Number(resumeState.detailInput));
    resumeState.detailResult = resp; applyResumeSelection(resp);
  } catch (err) { setMessage(getErrorMessage(err), true); }
  finally { setLoading("resumeDetail", false); }
}
async function saveJob() {
  if (!jobState.form.title || !jobState.form.jd_text) { setMessage("请填写岗位名称和 JD。", true); return; }
  setLoading("jobCreate", true);
  try {
    const resp = await jobApi.createJob({ company: jobState.form.company || null, title: jobState.form.title, jd_text: jobState.form.jd_text });
    applyJobSelection({ id: resp.job_id, local_job_id: resp.local_job_id, company: jobState.form.company, title: jobState.form.title, jd_text: jobState.form.jd_text });
    await fetchJobList();
  } catch (err) { setMessage(getErrorMessage(err), true); }
  finally { setLoading("jobCreate", false); }
}
async function fetchJobDetail() {
  if (!jobState.detailInput) { setMessage("请输入本地岗位编号。", true); return; }
  setLoading("jobDetail", true);
  try {
    const resp = await jobApi.getJobByLocalId(Number(jobState.detailInput));
    jobState.detailResult = resp; applyJobSelection(resp);
  } catch (err) { setMessage(getErrorMessage(err), true); }
  finally { setLoading("jobDetail", false); }
}
async function buildKnowledge() {
  setLoading("knowledgeBuild", true);
  try { knowledgeState.buildResult = await knowledgeApi.buildKnowledge(); setMessage("知识库构建完成。"); }
  catch (err) { setMessage(getErrorMessage(err), true); }
  finally { setLoading("knowledgeBuild", false); }
}
async function searchKnowledge() {
  if (!knowledgeState.searchQuery.trim()) { setMessage("请输入检索内容。", true); return; }
  setLoading("knowledgeSearch", true);
  try { knowledgeState.searchResult = await knowledgeApi.searchKnowledge(knowledgeState.searchQuery.trim(), Number(knowledgeState.topK) || 5); }
  catch (err) { setMessage(getErrorMessage(err), true); }
  finally { setLoading("knowledgeSearch", false); }
}
async function runRecommendJobs() {
  if (!currentResume.id) { setMessage("请先选择当前简历。", true); return; }
  setLoading("recommend", true);
  try {
    recommendState.result = await agentApi.recommendJobs({ resume_id: Number(currentResume.id), top_k: Number(recommendState.topK) || 5, max_jobs: Number(recommendState.maxJobs) || 10 });
    await fetchTasks();
  } catch (err) { setMessage(getErrorMessage(err), true); }
  finally { setLoading("recommend", false); }
}

/* ── Copilot 对话 ── */

// 意图 → 工具映射：根据用户输入关键词判断要跑哪些工具
function resolveTools(text) {
  const t = text.toLowerCase();
  const has = (keywords) => keywords.some(k => t.includes(k));
  if (has(['全面', '完整', '备战', '流程', '一条龙'])) return null; // null = 全跑
  const tools = [];
  if (has(['匹配', '分析', '评分', '对比', '合适', '适合'])) tools.push('match_analyze');
  if (has(['优化', '改进', '修改简历', '润色', '完善简历'])) tools.push('optimize_resume');
  if (has(['面试', '题目', '考题', '问答', '提问'])) tools.push('generate_interview_questions');
  return tools.length > 0 ? tools : null; // 没匹配到也全跑
}

function sendChatMessage() {
  const text = chatInput.value.trim();
  if (!text || chatRunning.value) return;
  if (!ensureResumeAndJob()) return;

  addChatMessage({ role: "user", text });
  chatInput.value = "";

  const tools = resolveTools(text);

  // 消息骨架
  const copilotMsg = { role: "copilot", steps: [], final: null, error: null };
  addChatMessage(copilotMsg);

  chatRunning.value = true;
  chatCancelFn.value = copilotApi.streamRun(
    { goal: text, resume_id: Number(currentResume.id), job_id: Number(currentJob.id), tools },
    {
      onStepStart(data) {
        copilotMsg.steps.push({ tool: data.tool, label: COPILOT_TOOL_LABELS[data.tool] || data.tool, status: "running", summary: null, error: null });
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
      onFinal(data) {
        copilotMsg.final = data;
        chatRunning.value = false;
        fetchTasks();
      },
      onError(err) {
        copilotMsg.error = typeof err === "string" ? err : JSON.stringify(err);
        chatRunning.value = false;
      },
    }
  );
}

function cancelChat() {
  if (chatCancelFn.value) { chatCancelFn.value(); chatCancelFn.value = null; }
  chatRunning.value = false;
}

/* ── 生命周期 ── */
onMounted(() => {
  setUnauthorizedHandler(() => clearSession());
  restoreSession();
});
onUnmounted(() => setUnauthorizedHandler(null));
</script>

<template>
  <div class="root-app">
    <!-- ═══════════ 登录页 ═══════════ -->
    <template v-if="!isLoggedIn">
      <div class="auth-shell">
        <div class="auth-card">
          <div class="auth-brand">
            <div class="brand-mark">JA</div>
            <div><h1>JobAgent</h1><p>AI 求职助手</p></div>
          </div>
          <div class="auth-switch">
            <button class="auth-tab" :class="{ active: authMode === 'login' }" @click="authMode = 'login'">登录</button>
            <button class="auth-tab" :class="{ active: authMode === 'register' }" @click="authMode = 'register'">注册</button>
          </div>
          <div class="form-stack">
            <label class="field"><span>用户名</span><input v-model="authForm.username" type="text" placeholder="请输入用户名" /></label>
            <label class="field"><span>密码</span><input v-model="authForm.password" type="password" placeholder="请输入密码" @keyup.enter="submitAuth" /></label>
          </div>
          <div v-if="error" class="alert alert-error">{{ error }}</div>
          <div v-else-if="message" class="alert alert-info">{{ message }}</div>
          <button class="btn btn-primary btn-block" :disabled="loadingMap.auth" @click="submitAuth">
            {{ loadingMap.auth ? "处理中..." : authMode === "login" ? "登录" : "注册并进入" }}
          </button>
        </div>
      </div>
    </template>

    <!-- ═══════════ 主界面 ═══════════ -->
    <template v-else>
      <div class="app-shell">
        <!-- ── 侧边栏 ── -->
        <aside class="sidebar">
          <div class="sidebar-brand">
            <div class="sidebar-logo">JA</div>
            <div><strong>JobAgent</strong><p>AI Copilot</p></div>
          </div>
          <nav class="sidebar-nav">
            <button v-for="item in sidebarItems" :key="item.key"
              class="nav-item"
              :class="{ active: activePanel === item.key || (item.key === 'chat' && !activePanel) }"
              @click="item.key === 'chat' ? closePanel() : togglePanel(item.key)">
              <span class="nav-icon">{{ item.icon }}</span>
              <span>{{ item.label }}</span>
            </button>
          </nav>
          <div class="sidebar-panel">
            <span>当前简历</span>
            <strong>{{ currentResume.localId ? `#${currentResume.localId}` : "未选择" }}</strong>
          </div>
          <div class="sidebar-panel">
            <span>当前岗位</span>
            <strong>{{ currentJob.localId ? `#${currentJob.localId}` : "未选择" }}</strong>
          </div>
          <div class="sidebar-footer">
            <div class="user-chip-inline"><span>👤</span><strong>{{ currentUser?.username }}</strong></div>
            <button class="btn btn-secondary btn-small" @click="logout">退出</button>
          </div>
        </aside>

        <!-- ── 主视图 ── -->
        <div class="main-shell">
          <!-- 全局消息条 -->
          <div v-if="error" class="toast toast-error" @click="error=''">{{ error }}</div>
          <div v-else-if="message" class="toast toast-info" @click="message=''">{{ message }}</div>

          <!-- 对话区 -->
          <div class="chat-area">
            <div class="chat-messages" ref="chatContainer">
              <div v-for="(msg, idx) in chatMessages" :key="idx" class="msg-wrapper" :class="msg.role">
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

                    <!-- 匹配分析结果 -->
                    <div v-if="step.status === 'done' && step.summary?.analysis" class="step-detail">
                      <div v-if="step.summary.analysis.match_score !== undefined" class="match-score-big">
                        {{ step.summary.analysis.match_score }}<span>分</span>
                      </div>
                      <div v-if="step.summary.analysis.match_reason" class="detail-item">
                        <p>{{ step.summary.analysis.match_reason }}</p>
                      </div>
                      <div v-if="normalizeToArray(step.summary.analysis.advantages).length" class="detail-item">
                        <h6>优势</h6>
                        <ul><li v-for="a in normalizeToArray(step.summary.analysis.advantages)" :key="a">{{ a }}</li></ul>
                      </div>
                      <div v-if="normalizeToArray(step.summary.analysis.weaknesses).length" class="detail-item">
                        <h6>不足</h6>
                        <ul><li v-for="w in normalizeToArray(step.summary.analysis.weaknesses)" :key="w">{{ w }}</li></ul>
                      </div>
                      <div v-if="normalizeToArray(step.summary.analysis.suggestions).length" class="detail-item">
                        <h6>建议</h6>
                        <ul><li v-for="s in normalizeToArray(step.summary.analysis.suggestions)" :key="s">{{ s }}</li></ul>
                      </div>
                    </div>

                    <!-- 简历优化结果 -->
                    <div v-if="step.status === 'done' && step.summary?.optimization" class="step-detail">
                      <p v-if="step.summary.optimization.summary" class="detail-text">{{ step.summary.optimization.summary }}</p>
                      <div v-if="normalizeToArray(step.summary.optimization.skill_keywords).length" class="detail-item">
                        <h6>技能关键词</h6>
                        <div class="tag-list"><span v-for="k in normalizeToArray(step.summary.optimization.skill_keywords)" :key="k" class="tag">{{ k }}</span></div>
                      </div>
                      <div v-if="normalizeToArray(step.summary.optimization.project_suggestions).length" class="detail-item">
                        <h6>项目建议</h6>
                        <ul><li v-for="p in normalizeToArray(step.summary.optimization.project_suggestions)" :key="p">{{ p }}</li></ul>
                      </div>
                      <div v-if="normalizeToArray(step.summary.optimization.resume_rewrite_suggestions).length" class="detail-item">
                        <h6>改写建议</h6>
                        <ul><li v-for="r in normalizeToArray(step.summary.optimization.resume_rewrite_suggestions)" :key="r">{{ r }}</li></ul>
                      </div>
                      <div v-if="normalizeToArray(step.summary.optimization.risk_points).length" class="detail-item">
                        <h6>风险点</h6>
                        <ul><li v-for="r in normalizeToArray(step.summary.optimization.risk_points)" :key="r">{{ r }}</li></ul>
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
                        <div v-if="normalizeToArray(step.summary.questions[group.key]).length" class="detail-item">
                          <h6>{{ group.label }}（{{ normalizeToArray(step.summary.questions[group.key]).length }}）</h6>
                          <div v-for="(q, qi) in normalizeToArray(step.summary.questions[group.key])" :key="qi" class="question-item">
                            <strong>{{ qi + 1 }}. {{ q.question || q.title || q }}</strong>
                            <small v-if="q.why_ask"><em>为什么问：</em>{{ q.why_ask }}</small>
                            <small v-if="q.answer_hint"><em>回答提示：</em>{{ q.answer_hint }}</small>
                          </div>
                        </div>
                      </template>
                    </div>
                  </div>
                  <div v-if="msg.final" class="msg-final">
                    <p>{{ msg.final.summary }}</p>
                  </div>
                  <div v-if="msg.error" class="msg-error">{{ msg.error }}</div>
                </div>
              </div>
              <!-- 执行中指示器 -->
              <div v-if="chatRunning" class="msg-wrapper copilot">
                <div class="msg-bubble copilot-bubble typing">处理中<span class="dots"></span></div>
              </div>
            </div>

            <!-- 输入区 -->
            <div class="chat-input-bar">
              <div class="quick-actions">
                <button class="btn btn-ghost btn-small" @click="togglePanel('resume')">📄 简历管理</button>
                <button class="btn btn-ghost btn-small" @click="togglePanel('job')">💼 新建岗位</button>
                <button class="btn btn-ghost btn-small" :disabled="chatRunning || !currentResume.id || !currentJob.id" @click="chatInput='全面备战'; sendChatMessage()">🚀 一键备战</button>
              </div>
              <div class="input-row">
                <input v-model="chatInput" type="text" class="chat-input"
                  placeholder="输入你的需求，如「帮我全面备战这个岗位」"
                  :disabled="chatRunning"
                  @keyup.enter="sendChatMessage" />
                <button class="btn btn-primary" :disabled="chatRunning || !chatInput.trim()" @click="sendChatMessage">发送</button>
                <button v-if="chatRunning" class="btn btn-secondary" @click="cancelChat">取消</button>
              </div>
            </div>
          </div>

          <!-- 滑出面板遮罩 -->
          <div v-if="activePanel" class="panel-overlay" @click="closePanel">
            <div class="slide-panel" @click.stop>
              <div class="panel-header">
                <h4>{{ sidebarItems.find(i => i.key === activePanel)?.label || '' }}</h4>
                <button class="btn btn-ghost btn-small" @click="closePanel">✕</button>
              </div>
              <div class="panel-body">
                <!-- ── 简历面板 ── -->
                <template v-if="activePanel === 'resume'">
                  <div class="form-stack">
                    <label class="field"><span>上传简历文件</span><input type="file" accept=".pdf,.docx,.txt" @change="onResumeFileChange" /></label>
                    <button class="btn btn-primary" :disabled="loadingMap.resumeUpload" @click="uploadResume">{{ loadingMap.resumeUpload ? "上传中..." : "上传" }}</button>
                  </div>
                  <hr />
                  <div class="inline-form">
                    <input v-model="resumeState.detailInput" type="number" min="1" placeholder="本地编号" />
                    <button class="btn btn-secondary" :disabled="loadingMap.resumeDetail" @click="fetchResumeDetail">查询</button>
                    <button class="btn btn-secondary" @click="fetchResumeList">刷新列表</button>
                  </div>
                  <div v-if="resumeState.list.length" class="result-list section-top">
                    <div v-for="item in resumeState.list" :key="item.id" class="result-card">
                      <div class="result-card-head">
                        <div><h5>#{{ item.local_resume_id }} {{ item.file_name }}</h5></div>
                        <button class="btn btn-secondary btn-small" @click="applyResumeSelection(item); closePanel()">选用</button>
                      </div>
                      <p>{{ item.content_preview || "暂无预览" }}</p>
                    </div>
                  </div>
                </template>

                <!-- ── 岗位面板 ── -->
                <template v-else-if="activePanel === 'job'">
                  <div class="form-stack">
                    <label class="field"><span>公司</span><input v-model="jobState.form.company" placeholder="如：字节跳动" /></label>
                    <label class="field"><span>岗位</span><input v-model="jobState.form.title" placeholder="如：后端开发工程师" /></label>
                    <label class="field"><span>岗位 JD</span><textarea v-model="jobState.form.jd_text" placeholder="粘贴 JD 内容"></textarea></label>
                    <button class="btn btn-primary" :disabled="loadingMap.jobCreate" @click="saveJob">{{ loadingMap.jobCreate ? "保存中..." : "保存岗位" }}</button>
                  </div>
                  <hr />
                  <div class="inline-form">
                    <input v-model="jobState.detailInput" type="number" min="1" placeholder="本地编号" />
                    <button class="btn btn-secondary" :disabled="loadingMap.jobDetail" @click="fetchJobDetail">查询</button>
                    <button class="btn btn-secondary" @click="fetchJobList">刷新列表</button>
                  </div>
                  <div v-if="jobState.list.length" class="result-list section-top">
                    <div v-for="item in jobState.list" :key="item.id" class="result-card">
                      <div class="result-card-head">
                        <div><h5>#{{ item.local_job_id }} {{ item.company || "?" }} / {{ item.title }}</h5></div>
                        <button class="btn btn-secondary btn-small" @click="applyJobSelection(item); closePanel()">选用</button>
                      </div>
                      <p>{{ item.jd_preview || "暂无内容" }}</p>
                    </div>
                  </div>
                </template>

                <!-- ── 推荐面板 ── -->
                <template v-else-if="activePanel === 'recommend'">
                  <div class="grid form-grid">
                    <label class="field"><span>Top K</span><input v-model="recommendState.topK" type="number" min="1" max="10" /></label>
                    <label class="field"><span>Max Jobs</span><input v-model="recommendState.maxJobs" type="number" min="1" max="20" /></label>
                  </div>
                  <button class="btn btn-primary" :disabled="loadingMap.recommend" @click="runRecommendJobs">{{ loadingMap.recommend ? "推荐中..." : "开始推荐" }}</button>
                  <div v-if="recommendState.result?.items?.length" class="result-list section-top">
                    <div v-for="item in recommendState.result.items" :key="item.job_id" class="result-card">
                      <div class="result-card-head">
                        <div><h5>{{ item.company || "?" }} / {{ item.title }}</h5><p>匹配 {{ getMatchScore(item) }} 分</p></div>
                        <button class="btn btn-secondary btn-small" @click="applyJobSelection({ id: item.job_id, local_job_id: item.local_job_id, company: item.company, title: item.title }); closePanel()">选用</button>
                      </div>
                      <p>{{ item.match_reason || "" }}</p>
                    </div>
                  </div>
                </template>

                <!-- ── 任务面板 ── -->
                <template v-else-if="activePanel === 'task'">
                  <div class="inline-form">
                    <input v-model="taskState.filterTaskType" placeholder="如 MATCH_ANALYZE" />
                    <button class="btn btn-secondary" @click="fetchTasks">刷新</button>
                  </div>
                  <div class="table-wrap section-top">
                    <table class="task-table">
                      <thead><tr><th>ID</th><th>类型</th><th>状态</th><th>时间</th><th></th></tr></thead>
                      <tbody>
                        <tr v-for="t in taskState.items" :key="t.id">
                          <td>{{ t.id }}</td><td>{{ t.task_type }}</td><td>{{ t.status }}</td><td>{{ t.created_at }}</td>
                          <td><button class="btn btn-secondary btn-small" @click="fetchTaskDetail(t.id)">详情</button></td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                  <div v-if="taskState.selectedTask" class="task-detail section-top">
                    <div class="task-detail-head">
                      <h5>任务 #{{ taskState.selectedTask.id }} 详情</h5>
                      <button class="btn btn-ghost btn-small" @click="taskState.selectedTask = null">✕ 关闭</button>
                    </div>
                    <div class="info-list">
                      <div class="info-item"><span>类型</span><strong>{{ taskState.selectedTask.task_type }}</strong></div>
                      <div class="info-item"><span>状态</span><strong>{{ taskState.selectedTask.status }}</strong></div>
                      <div class="info-item"><span>简历ID</span><strong>{{ taskState.selectedTask.resume_id ?? '-' }}</strong></div>
                      <div class="info-item"><span>岗位ID</span><strong>{{ taskState.selectedTask.job_id ?? '-' }}</strong></div>
                    </div>
                    <div v-if="taskState.selectedTask.output_json" class="section-top">
                      <h5>结果</h5>
                      <pre class="code-block">{{ formatJson(taskState.selectedTask.output_json) }}</pre>
                    </div>
                    <div v-if="taskState.selectedTask.error_msg" class="section-top">
                      <h5>错误信息</h5>
                      <pre class="code-block error-block">{{ taskState.selectedTask.error_msg }}</pre>
                    </div>
                  </div>
                </template>

                <!-- ── 知识库面板 ── -->
                <template v-else-if="activePanel === 'knowledge'">
                  <button class="btn btn-primary btn-block" :disabled="loadingMap.knowledgeBuild" @click="buildKnowledge">{{ loadingMap.knowledgeBuild ? "构建中..." : "构建知识库" }}</button>
                  <div v-if="knowledgeState.buildResult" class="info-list section-top">
                    <div class="info-item"><span>文件数</span><strong>{{ knowledgeState.buildResult.file_count }}</strong></div>
                    <div class="info-item"><span>切片数</span><strong>{{ knowledgeState.buildResult.chunk_count }}</strong></div>
                  </div>
                  <hr />
                  <div class="form-stack">
                    <label class="field"><span>Query</span><input v-model="knowledgeState.searchQuery" placeholder="如 Spring Boot 面试题" /></label>
                    <label class="field"><span>Top K</span><input v-model="knowledgeState.topK" type="number" min="1" max="20" /></label>
                    <button class="btn btn-secondary" :disabled="loadingMap.knowledgeSearch" @click="searchKnowledge">检索</button>
                  </div>
                  <div v-if="knowledgeState.searchResult?.items?.length" class="result-list section-top">
                    <div v-for="(item, idx) in knowledgeState.searchResult.items" :key="idx" class="result-card">
                      <h5>{{ item.title || "知识片段" }}</h5>
                      <small>{{ item.source }}</small>
                      <p>{{ item.clean_content || item.content || "" }}</p>
                    </div>
                  </div>
                </template>
              </div>
            </div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
/* ── 基础 ── */
:global(html, body, #app) { margin: 0; min-height: 100%; background: #f8fafc; color: #0f172a; font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
:global(*) { box-sizing: border-box; }
.root-app { min-height: 100vh; }

/* ── 登录 ── */
.auth-shell { min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 24px; background: radial-gradient(circle at top left, rgba(37,99,235,0.12), transparent 22%), linear-gradient(180deg, #eff6ff 0%, #f8fafc 100%); }
.auth-card { width: min(400px, 100%); background: #fff; border: 1px solid #e5e7eb; border-radius: 20px; box-shadow: 0 24px 60px rgba(15,23,42,0.08); padding: 28px; }
.auth-brand { display: flex; align-items: center; gap: 14px; margin-bottom: 24px; }
.brand-mark { width: 48px; height: 48px; display: inline-flex; align-items: center; justify-content: center; border-radius: 14px; background: #0f172a; color: #fff; font-weight: 700; }
.auth-brand h1 { margin: 0 0 4px; font-size: 26px; }
.auth-brand p { margin: 0; color: #64748b; font-size: 14px; }
.auth-switch { display: inline-flex; width: 100%; padding: 4px; border-radius: 12px; background: #f1f5f9; margin-bottom: 20px; }
.auth-tab { flex: 1; height: 40px; border: none; border-radius: 10px; background: transparent; color: #475569; font-size: 14px; font-weight: 600; cursor: pointer; }
.auth-tab.active { background: #fff; color: #0f172a; box-shadow: 0 1px 2px rgba(15,23,42,0.08); }

/* ── 布局 ── */
.app-shell { display: flex; min-height: 100vh; }
.sidebar { position: fixed; left: 0; top: 0; bottom: 0; width: 220px; background: #0f172a; color: #cbd5e1; padding: 20px 12px; display: flex; flex-direction: column; overflow-y: auto; z-index: 20; }
.sidebar-brand { display: flex; align-items: center; gap: 10px; margin-bottom: 20px; padding: 0 8px; }
.sidebar-logo { width: 38px; height: 38px; display: inline-flex; align-items: center; justify-content: center; border-radius: 10px; background: #2563eb; color: #fff; font-weight: 700; font-size: 14px; }
.sidebar-brand strong { display: block; color: #fff; font-size: 15px; }
.sidebar-brand p { margin: 2px 0 0; color: #94a3b8; font-size: 11px; }
.sidebar-nav { display: flex; flex-direction: column; gap: 4px; flex: 1; }
.nav-item { height: 40px; width: 100%; padding: 0 12px; border: none; border-radius: 10px; background: transparent; color: #cbd5e1; text-align: left; font-size: 14px; cursor: pointer; display: flex; align-items: center; gap: 10px; }
.nav-item:hover { background: #1e293b; }
.nav-item.active { background: #2563eb; color: #fff; }
.nav-icon { width: 22px; text-align: center; }
.sidebar-panel { margin-top: 8px; padding: 12px; border-radius: 12px; background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.06); }
.sidebar-panel span, .sidebar-panel small { display: block; color: #94a3b8; font-size: 11px; }
.sidebar-panel strong { color: #fff; font-size: 15px; }
.sidebar-footer { margin-top: 12px; padding-top: 12px; border-top: 1px solid rgba(255,255,255,0.08); display: flex; align-items: center; justify-content: space-between; }
.user-chip-inline { display: flex; align-items: center; gap: 6px; color: #cbd5e1; font-size: 13px; }

/* ── 主视图 ── */
.main-shell { margin-left: 220px; width: calc(100% - 220px); min-height: 100vh; display: flex; flex-direction: column; position: relative; }
.toast { padding: 10px 16px; font-size: 13px; text-align: center; cursor: pointer; }
.toast-error { background: #fef2f2; color: #b91c1c; border-bottom: 1px solid #fecaca; }
.toast-info { background: #ecfdf5; color: #047857; border-bottom: 1px solid #a7f3d0; }

/* ── 对话区 ── */
.chat-area { flex: 1; display: flex; flex-direction: column; max-width: 800px; width: 100%; margin: 0 auto; padding: 0 24px; height: calc(100vh - 0px); }
.chat-messages { flex: 1; overflow-y: auto; padding: 24px 0; }
.msg-wrapper { margin-bottom: 16px; max-width: 85%; }
.msg-wrapper.user { margin-left: auto; }
.msg-wrapper.copilot { margin-right: auto; }
.msg-bubble { padding: 12px 16px; border-radius: 16px; font-size: 14px; line-height: 1.7; }
.user-bubble { background: #2563eb; color: #fff; border-bottom-right-radius: 4px; }
.copilot-bubble { background: #fff; border: 1px solid #e5e7eb; border-bottom-left-radius: 4px; }
.msg-card { background: #fff; border: 1px solid #e5e7eb; border-radius: 14px; padding: 16px; width: 100%; }
.msg-card-title { font-weight: 700; margin-bottom: 10px; font-size: 14px; }
.step-row { padding: 6px 0; font-size: 13px; display: flex; align-items: center; gap: 8px; }
.step-block { margin-bottom: 10px; }
.step-block.step-done {  }
.step-row { display: flex; align-items: center; gap: 8px; padding: 6px 0; }
.step-icon { width: 20px; }
.step-label { flex: 1; font-size: 13px; }
.step-detail { margin-top: 8px; padding: 12px 14px; background: #f8fafc; border-radius: 10px; border: 1px solid #e5e7eb; }
.match-score-big { font-size: 32px; font-weight: 800; color: #2563eb; text-align: center; padding: 12px 0; }
.match-score-big span { font-size: 16px; font-weight: 600; color: #64748b; }
.detail-item { margin-top: 10px; }
.detail-item h6 { margin: 0 0 6px; font-size: 13px; color: #334155; }
.detail-item ul { margin: 0; padding-left: 18px; font-size: 13px; line-height: 1.8; color: #334155; }
.detail-text { font-size: 13px; color: #334155; line-height: 1.7; }
.tag-list { display: flex; flex-wrap: wrap; gap: 6px; }
.tag { display: inline-block; padding: 2px 10px; background: #eff6ff; color: #2563eb; border-radius: 8px; font-size: 12px; font-weight: 600; }
.question-item { margin-top: 10px; padding: 10px 12px; background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; }
.question-item strong { display: block; font-size: 13px; color: #0f172a; margin-bottom: 4px; }
.question-item small { display: block; color: #64748b; font-size: 12px; line-height: 1.6; margin-top: 2px; }
.question-item small em { color: #94a3b8; font-style: normal; margin-right: 4px; }
.msg-final { margin-top: 12px; padding-top: 10px; border-top: 1px solid #e5e7eb; }
.msg-final p { margin: 0 0 6px; font-size: 14px; }
.msg-final small { color: #64748b; font-size: 12px; }
.msg-error { color: #b91c1c; font-size: 13px; margin-top: 6px; }
.msg-text { white-space: pre-wrap; }
.typing .dots::after { content: "..."; animation: dots 1.5s steps(4, end) infinite; }
@keyframes dots { 0%, 20% { content: ""; } 40% { content: "."; } 60% { content: ".."; } 80%, 100% { content: "..."; } }

/* ── 输入区 ── */
.chat-input-bar { padding: 16px 0; border-top: 1px solid #e5e7eb; background: #f8fafc; }
.quick-actions { display: flex; gap: 8px; margin-bottom: 10px; }
.input-row { display: flex; gap: 10px; }
.chat-input { flex: 1; height: 44px; border: 1px solid #cbd5e1; border-radius: 22px; padding: 0 18px; font-size: 14px; outline: none; background: #fff; }
.chat-input:focus { border-color: #2563eb; box-shadow: 0 0 0 3px rgba(37,99,235,0.1); }
.chat-input:disabled { background: #f1f5f9; }

/* ── 滑出面板 ── */
.panel-overlay { position: fixed; inset: 0; background: rgba(15,23,42,0.3); z-index: 30; display: flex; justify-content: flex-end; }
.slide-panel { width: min(480px, 90vw); height: 100%; background: #fff; overflow-y: auto; box-shadow: -8px 0 30px rgba(15,23,42,0.1); }
.panel-header { display: flex; align-items: center; justify-content: space-between; padding: 18px 24px; border-bottom: 1px solid #e5e7eb; position: sticky; top: 0; background: #fff; z-index: 2; }
.panel-header h4 { margin: 0; font-size: 18px; }
.panel-body { padding: 24px; }

/* ── 通用组件 ── */
.form-stack { display: grid; gap: 14px; }
.form-grid { margin-bottom: 14px; }
.grid { display: grid; gap: 16px; grid-template-columns: repeat(2, minmax(0, 1fr)); }
.field span { display: block; margin-bottom: 6px; color: #334155; font-size: 13px; font-weight: 600; }
input, textarea { width: 100%; border: 1px solid #cbd5e1; border-radius: 10px; padding: 10px 12px; font-size: 14px; outline: none; }
input { height: 40px; }
textarea { min-height: 140px; resize: vertical; }
input:focus, textarea:focus { border-color: #2563eb; box-shadow: 0 0 0 3px rgba(37,99,235,0.1); }
.btn { border: none; border-radius: 10px; height: 40px; padding: 0 16px; font-weight: 600; font-size: 14px; cursor: pointer; }
.btn:disabled { opacity: 0.6; cursor: not-allowed; }
.btn-block { width: 100%; }
.btn-primary { background: #2563eb; color: #fff; }
.btn-secondary { background: #fff; color: #334155; border: 1px solid #cbd5e1; }
.btn-ghost { background: transparent; color: #64748b; border: 1px solid #e5e7eb; }
.btn-small { height: 34px; padding: 0 12px; font-size: 13px; }
.alert { border-radius: 12px; padding: 12px 14px; margin-bottom: 20px; font-size: 14px; line-height: 1.6; }
.alert-error { background: #fef2f2; color: #b91c1c; border: 1px solid #fecaca; }
.alert-info { background: #eff6ff; color: #1d4ed8; border: 1px solid #bfdbfe; }
.inline-form { display: flex; gap: 10px; align-items: center; margin-top: 14px; }
.inline-form input { flex: 1; }
.section-top { margin-top: 16px; }
.result-list { display: grid; gap: 10px; }
.result-card { border: 1px solid #e5e7eb; border-radius: 12px; background: #f8fafc; padding: 14px 16px; }
.result-card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.result-card h5 { margin: 0 0 6px; font-size: 14px; }
.result-card p, .result-card small { margin: 0; color: #64748b; font-size: 12px; line-height: 1.6; }
.info-list { display: grid; gap: 10px; }
.info-item { border: 1px solid #e5e7eb; border-radius: 10px; background: #f8fafc; padding: 12px 14px; }
.info-item span { display: block; margin-bottom: 4px; color: #64748b; font-size: 11px; }
.info-item strong { color: #0f172a; }
.table-wrap { overflow: auto; }
.task-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.task-table th, .task-table td { padding: 10px 12px; border-bottom: 1px solid #e5e7eb; text-align: left; }
.task-table th { background: #f8fafc; color: #64748b; font-weight: 700; }
.task-detail { background: #f8fafc; border: 1px solid #e5e7eb; border-radius: 12px; padding: 16px; }
.task-detail-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.task-detail h5 { margin: 0 0 10px; font-size: 14px; }
.error-block { background: #450a0a; color: #fecaca; }

.code-block { margin: 0; max-height: 240px; overflow: auto; border-radius: 10px; padding: 14px; background: #0f172a; color: #e2e8f0; font-size: 12px; line-height: 1.6; }
hr { border: none; border-top: 1px solid #e5e7eb; margin: 18px 0; }

/* ── 响应式 ── */
@media (max-width: 900px) { .sidebar { width: 200px; } .main-shell { margin-left: 200px; width: calc(100% - 200px); } .chat-area { padding: 0 16px; } .msg-wrapper { max-width: 92%; } }
@media (max-width: 720px) { .sidebar { width: 180px; } .main-shell { margin-left: 180px; width: calc(100% - 180px); } .grid { grid-template-columns: 1fr; } .quick-actions { flex-wrap: wrap; } }
</style>
