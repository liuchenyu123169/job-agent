<script setup>
import { computed, onMounted, onUnmounted, provide, reactive, ref } from "vue";
import {
  adminApi, agentApi, authApi, copilotApi, jobApi, knowledgeApi, resumeApi,
  setUnauthorizedHandler, taskApi
} from "./api";
import { getErrorMessage } from "./components/utils.js";
import AuthForm from "./components/AuthForm.vue";
import ChatPanel from "./components/ChatPanel.vue";
import ResumePanel from "./components/ResumePanel.vue";
import JobPanel from "./components/JobPanel.vue";
import RecommendPanel from "./components/RecommendPanel.vue";
import TaskPanel from "./components/TaskPanel.vue";
import AdminDashboard from "./components/AdminDashboard.vue";
import AdminJobs from "./components/AdminJobs.vue";
import AdminResumes from "./components/AdminResumes.vue";
import AdminSessions from "./components/AdminSessions.vue";
import AdminTasks from "./components/AdminTasks.vue";
import AdminTraces from "./components/AdminTraces.vue";
import AdminUsers from "./components/AdminUsers.vue";
import KnowledgePanel from "./components/KnowledgePanel.vue";

/* ── 侧边栏 ── */
const baseSidebarItems = [
  { key: "chat",      label: "对话",      icon: "💬" },
  { key: "resume",    label: "简历管理",  icon: "📄" },
  { key: "job",       label: "岗位管理",  icon: "💼" },
  { key: "recommend", label: "岗位推荐",  icon: "🔍" },
  { key: "task",      label: "任务记录",  icon: "📋" },
];
const adminSidebarItems = [
  { key: "admin_dashboard", label: "管理仪表盘", icon: "📊" },
  { key: "admin_users",     label: "用户管理",   icon: "👥" },
  { key: "admin_resumes",   label: "全局简历",   icon: "📄" },
  { key: "admin_jobs",      label: "全局岗位",   icon: "💼" },
  { key: "admin_tasks",     label: "全局任务",   icon: "📋" },
  { key: "admin_sessions",  label: "全局会话",   icon: "💬" },
  { key: "admin_traces",    label: "链路追踪",   icon: "🔍" },
  { key: "knowledge",       label: "RAG 知识库", icon: "⚙️" },
  { key: "evaluation",      label: "评测",       icon: "📊" },
];

const sidebarItems = computed(() => {
  if (currentUser.value?.is_admin) return adminSidebarItems;
  return baseSidebarItems;
});
const activeView = ref("chat");  // 当前主视图：chat | resume | job | recommend | task | admin_* | knowledge | evaluation

/* ── 会话管理（侧边栏历史列表） ── */
const currentSessionId = ref(getStoredSessionId());
const sessions = ref([]);
const sessionsExpanded = ref(true);

function getStoredSessionId() {
  const stored = localStorage.getItem("currentSessionId");
  return stored ? Number(stored) : null;
}
function storeSessionId(id) {
  currentSessionId.value = id;
  localStorage.setItem("currentSessionId", String(id));
}
async function loadSessions() {
  try { sessions.value = await copilotApi.listSessions(20); } catch { /* 静默 */ }
}
async function selectSession(sessionId) {
  currentSessionId.value = sessionId;
  storeSessionId(sessionId);
  activeView.value = "chat"; // 切回对话视图
  if (chatRef.value) {
    await chatRef.value.loadSessionHistory(sessionId);
  }
}
async function newChat() {
  currentSessionId.value = null;
  localStorage.removeItem("currentSessionId");
  if (chatRef.value) {
    chatRef.value.messages = [];
    chatRef.value.welcome(currentUser.value?.username || "");
  }
}

async function deleteSession(sessionId, event) {
  event.stopPropagation(); // 避免触发 selectSession
  if (!confirm("确认删除此对话？")) return;
  try {
    await copilotApi.deleteSession(sessionId);
    // 删除的是当前会话 → 切回欢迎页
    if (currentSessionId.value === sessionId) {
      newChat();
    }
    await loadSessions();
  } catch (err) {
    setMessage(getErrorMessage(err), true);
  }
}

function truncateGoal(goal, maxLen = 18) {
  if (!goal) return '新对话';
  return goal.length > maxLen ? goal.slice(0, maxLen) + '...' : goal;
}

/* ── 认证状态 ── */
const token = ref(localStorage.getItem("token") || "");
const currentUser = ref(null);
const isLoggedIn = computed(() => Boolean(token.value && currentUser.value));

/* ── 全局消息（fixed 浮层 + 自动消失） ── */
const message = ref("");
const error = ref("");
const toastVisible = ref(false);
let toastTimer = null;

function setMessage(text, isError = false) {
  clearTimeout(toastTimer);
  if (isError) { error.value = text; message.value = ""; }
  else { message.value = text; error.value = ""; }
  toastVisible.value = true;
  toastTimer = setTimeout(() => {
    toastVisible.value = false;
    message.value = "";
    error.value = "";
  }, 3000);
}

/* ── 当前选中资源 ── */
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

/* ── 子组件引用 ── */
const chatRef = ref(null);
const resumeRef = ref(null);
const jobRef = ref(null);
const taskRef = ref(null);

/* ── 资源选择 ── */
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

/* ── 数据刷新 ── */
async function fetchResumeList() {
  if (!isLoggedIn.value) return;
  loadingMap.resumeList = true;
  try { if (resumeRef.value) resumeRef.value.list = (await resumeApi.listResumes()).items || []; }
  catch (err) { setMessage(getErrorMessage(err), true); }
  finally { loadingMap.resumeList = false; }
}
async function fetchJobList() {
  if (!isLoggedIn.value) return;
  loadingMap.jobList = true;
  try { if (jobRef.value) jobRef.value.list = (await jobApi.listJobs()).items || []; }
  catch (err) { setMessage(getErrorMessage(err), true); }
  finally { loadingMap.jobList = false; }
}
async function fetchTasks() {
  if (!isLoggedIn.value) return;
  if (!taskRef.value) return;
  loadingMap.tasks = true;
  try { await taskRef.value.fetchTasks(); }
  catch (err) { setMessage(getErrorMessage(err), true); }
  finally { loadingMap.tasks = false; }
}

/* ── 认证生命周期 ── */
function clearSession(notify = true) {
  localStorage.removeItem("token");
  token.value = ""; currentUser.value = null;
  currentResume.id = null; currentResume.localId = null;
  currentResume.fileName = ""; currentResume.contentPreview = ""; currentResume.content = "";
  currentJob.id = null; currentJob.localId = null;
  currentJob.company = ""; currentJob.title = ""; currentJob.jdText = "";
  if (notify) setMessage("登录状态已失效，请重新登录。", true);
}

async function restoreSession() {
  if (!token.value) return;
  loadingMap.restore = true;
  try {
    currentUser.value = await authApi.getCurrentUser();
    chatRef.value?.welcome(currentUser.value?.username);
    await Promise.all([fetchResumeList(), fetchJobList(), fetchTasks()]);
  } catch (err) { clearSession(false); setMessage(getErrorMessage(err), true); }
  finally { loadingMap.restore = false; }
}

function onLoggedIn() {
  chatRef.value?.welcome(currentUser.value?.username);
}

function logout() { clearSession(false); setMessage("已退出登录。"); }

/* ── 评测 ── */
const evalWorkflows = ref(["match_analyze", "interview_questions", "resume_optimize", "resume_generate"]);
const evalWorkflow = ref("match_analyze");
const evalUseJudge = ref(true);
const evalRunning = ref(false);
const evalResult = ref(null);

async function runEvaluation() {
  evalRunning.value = true;
  evalResult.value = null;
  try {
    const resp = await fetch("http://127.0.0.1:8000/api/evaluation/run", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token.value}`,
      },
      body: JSON.stringify({
        workflows: [evalWorkflow.value],
        llm_judge: evalUseJudge.value,
        judge_samples: 3,
      }),
    });
    evalResult.value = await resp.json();
  } catch (err) {
    evalResult.value = { error: String(err) };
  }
  evalRunning.value = false;
}

/* ── 主视图切换 ── */
function switchView(key) {
  activeView.value = key;
}

/* ── provide 共享状态给子组件 ── */
provide("api", { adminApi, agentApi, authApi, copilotApi, jobApi, knowledgeApi, resumeApi, taskApi });
provide("setMessage", setMessage);
provide("loadingMap", loadingMap);
provide("token", token);
provide("currentUser", currentUser);
provide("currentResume", currentResume);
provide("currentJob", currentJob);
provide("applyResumeSelection", applyResumeSelection);
provide("applyJobSelection", applyJobSelection);
provide("fetchResumeList", fetchResumeList);
provide("fetchJobList", fetchJobList);
provide("fetchTasks", fetchTasks);
// 会话管理
provide("currentSessionId", currentSessionId);
provide("sessions", sessions);
provide("selectSession", selectSession);
provide("newChat", newChat);
provide("loadSessions", loadSessions);
provide("storeSessionId", storeSessionId);
provide("switchView", switchView);

onMounted(async () => {
  setUnauthorizedHandler(() => clearSession());
  await Promise.all([restoreSession(), loadSessions()]);

  // 自动恢复最近会话
  if (currentSessionId.value) {
    const found = sessions.value.find(s => s.id === currentSessionId.value);
    if (!found) {
      localStorage.removeItem("currentSessionId");
      currentSessionId.value = null;
    }
  }
  if (!currentSessionId.value && sessions.value.length > 0) {
    const recent = sessions.value.find(s => s.status !== "ERROR") || sessions.value[0];
    if (recent) await selectSession(recent.id);
  }
});
onUnmounted(() => setUnauthorizedHandler(null));
</script>

<template>
  <div class="root-app">
    <!-- ═══ 登录页 ═══ -->
    <template v-if="!isLoggedIn">
      <AuthForm @loggedIn="onLoggedIn" />
    </template>

    <!-- ═══ 主界面 ═══ -->
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
              :class="{ active: activeView === item.key }"
              @click="switchView(item.key)">
              <span class="nav-icon">{{ item.icon }}</span>
              <span>{{ item.label }}</span>
            </button>
            <!-- 会话历史（对话子列表） -->
            <div class="session-list" v-if="sessions.length > 0">
              <div class="session-list-header" @click="sessionsExpanded = !sessionsExpanded">
                <span class="session-list-arrow">{{ sessionsExpanded ? '▾' : '▸' }}</span>
                <span>历史对话</span>
                <button class="btn-new-chat" @click.stop="newChat()" title="新对话">＋</button>
              </div>
              <div class="session-list-items" v-show="sessionsExpanded">
                <button v-for="s in sessions" :key="s.id"
                  class="session-item"
                  :class="{ active: s.id === currentSessionId }"
                  @click="selectSession(s.id)">
                  <span class="session-goal">{{ truncateGoal(s.goal) }}</span>
                  <span class="session-date">{{ (s.created_at || '').slice(0, 10) }}</span>
                  <span class="session-delete" @click="deleteSession(s.id, $event)" title="删除此对话">✕</span>
                </button>
              </div>
            </div>
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

        <!-- ── 主视图（根据侧边栏选中项切换内容） ── -->
        <div class="main-shell">

          <ChatPanel ref="chatRef" v-if="activeView === 'chat'" />
          <ResumePanel ref="resumeRef" v-if="activeView === 'resume'" />
          <JobPanel ref="jobRef" v-if="activeView === 'job'" />
          <RecommendPanel v-if="activeView === 'recommend'" />
          <TaskPanel ref="taskRef" v-if="activeView === 'task'" />
          <AdminDashboard v-if="activeView === 'admin_dashboard'" />
          <AdminUsers v-if="activeView === 'admin_users'" />
          <AdminResumes v-if="activeView === 'admin_resumes'" />
          <AdminJobs v-if="activeView === 'admin_jobs'" />
          <AdminTasks v-if="activeView === 'admin_tasks'" />
          <AdminSessions v-if="activeView === 'admin_sessions'" />
          <AdminTraces v-if="activeView === 'admin_traces'" />
          <KnowledgePanel v-if="activeView === 'knowledge'" />
          <div v-if="activeView === 'evaluation'" class="eval-panel-inline section-top" style="padding:24px;max-width:600px;margin:0 auto;">
            <h4>自动化评测</h4>
            <p>选择 workflow 并运行评测，结果保存到 evaluation_results/ 目录。</p>
            <div class="form-stack">
              <div class="field"><span>Workflow</span>
                <select v-model="evalWorkflow" style="width:100%;height:40px;border-radius:10px;padding:0 12px;border:1px solid #cbd5e1;">
                  <option v-for="w in evalWorkflows" :key="w" :value="w">{{ w }}</option>
                </select>
              </div>
              <div class="field"><span>LLM Judge</span>
                <input type="checkbox" v-model="evalUseJudge" /> 启用 LLM 质量评分（耗时较长）
              </div>
              <button class="btn btn-primary" :disabled="evalRunning" @click="runEvaluation">
                {{ evalRunning ? '评测中...' : '运行评测' }}
              </button>
            </div>
            <div v-if="evalResult" style="margin-top:16px;background:#f8fafc;border-radius:12px;padding:16px;max-height:400px;overflow:auto;">
              <pre style="font-size:12px;white-space:pre-wrap;margin:0;">{{ JSON.stringify(evalResult, null, 2) }}</pre>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- ═══ 全局 Toast（fixed 浮层，自动消失） ═══ -->
    <Transition name="toast-fade">
      <div v-if="toastVisible && error" class="toast-overlay toast-overlay-error" @click="toastVisible=false">{{ error }}</div>
      <div v-else-if="toastVisible && message" class="toast-overlay toast-overlay-info" @click="toastVisible=false">{{ message }}</div>
    </Transition>
  </div>
</template>

<style scoped>
/* ── 基础 ── */
:global(html, body, #app) { margin: 0; min-height: 100%; background: #f8fafc; color: #0f172a; font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
:global(*) { box-sizing: border-box; }
.root-app { min-height: 100vh; }

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

/* ── 会话列表（侧边栏子列表） ── */
.session-list { margin-top: 4px; border-top: 1px solid rgba(255,255,255,0.06); padding-top: 6px; }
.session-list-header { display: flex; align-items: center; gap: 4px; padding: 6px 12px; color: #94a3b8; font-size: 11px; cursor: pointer; user-select: none; }
.session-list-header:hover { color: #cbd5e1; }
.session-list-arrow { width: 12px; font-size: 10px; }
.btn-new-chat { margin-left: auto; background: none; border: 1px solid rgba(255,255,255,0.1); color: #94a3b8; border-radius: 6px; width: 22px; height: 22px; font-size: 12px; line-height: 1; cursor: pointer; padding: 0; }
.btn-new-chat:hover { color: #fff; border-color: rgba(255,255,255,0.25); }
.session-list-items { display: flex; flex-direction: column; gap: 2px; max-height: 280px; overflow-y: auto; }
.session-item { width: 100%; padding: 6px 12px 6px 24px; border: none; border-radius: 8px; background: transparent; color: #94a3b8; text-align: left; font-size: 12px; cursor: pointer; display: flex; flex-direction: column; gap: 2px; }
.session-item:hover { background: rgba(255,255,255,0.04); color: #cbd5e1; }
.session-item.active { background: rgba(37,99,235,0.2); color: #fff; }
.session-goal { line-height: 1.4; }
.session-date { font-size: 10px; color: #64748b; }
.session-item.active .session-date { color: #93c5fd; }
.session-delete {
  position: absolute; right: 6px; top: 50%; transform: translateY(-50%);
  opacity: 0; font-size: 10px; color: #ef4444; padding: 2px 5px; border-radius: 4px;
  transition: opacity 0.15s; line-height: 1;
}
.session-item { position: relative; }
.session-item:hover .session-delete { opacity: 0.7; }
.session-item .session-delete:hover { opacity: 1; background: rgba(239, 68, 68, 0.15); }

/* ── 主视图 ── */
.main-shell { margin-left: 220px; width: calc(100% - 220px); min-height: 100vh; display: flex; flex-direction: column; position: relative; }
/* ── 全局 Toast（fixed 浮层，浮于所有内容之上） ── */
.toast-overlay {
  position: fixed; top: 20px; left: 50%; transform: translateX(-50%);
  padding: 12px 24px; font-size: 14px; border-radius: 12px; cursor: pointer;
  z-index: 9999; max-width: 520px; text-align: center;
  box-shadow: 0 8px 30px rgba(15,23,42,0.15);
  pointer-events: auto;
}
.toast-overlay-error { background: #fef2f2; color: #b91c1c; border: 1px solid #fecaca; }
.toast-overlay-info  { background: #ecfdf5; color: #047857; border: 1px solid #a7f3d0; }

/* Toast 进入/离开动画 */
.toast-fade-enter-active { transition: all 0.3s ease-out; }
.toast-fade-leave-active { transition: all 0.25s ease-in; }
.toast-fade-enter-from { opacity: 0; transform: translateX(-50%) translateY(-12px); }
.toast-fade-leave-to   { opacity: 0; transform: translateX(-50%) translateY(-8px); }

/* ── 面板 ── */

/* ── 全局子组件样式 ── */
:global(.form-stack) { display: grid; gap: 14px; }
:global(.form-grid) { margin-bottom: 14px; }
:global(.grid) { display: grid; gap: 16px; grid-template-columns: repeat(2, minmax(0, 1fr)); }
:global(.field span) { display: block; margin-bottom: 6px; color: #334155; font-size: 13px; font-weight: 600; }
:global(input), :global(textarea) { width: 100%; border: 1px solid #cbd5e1; border-radius: 10px; padding: 10px 12px; font-size: 14px; outline: none; }
:global(input) { height: 40px; }
:global(textarea) { min-height: 140px; resize: vertical; }
:global(input:focus), :global(textarea:focus) { border-color: #2563eb; box-shadow: 0 0 0 3px rgba(37,99,235,0.1); }
:global(.btn) { border: none; border-radius: 10px; height: 40px; padding: 0 16px; font-weight: 600; font-size: 14px; cursor: pointer; }
:global(.btn:disabled) { opacity: 0.6; cursor: not-allowed; }
:global(.btn-block) { width: 100%; }
:global(.btn-primary) { background: #2563eb; color: #fff; }
:global(.btn-secondary) { background: #fff; color: #334155; border: 1px solid #cbd5e1; }
:global(.btn-ghost) { background: transparent; color: #64748b; border: 1px solid #e5e7eb; }
:global(.btn-small) { height: 34px; padding: 0 12px; font-size: 13px; }
:global(.section-top) { margin-top: 16px; }
:global(.result-list) { display: grid; gap: 10px; }
:global(.result-card) { border: 1px solid #e5e7eb; border-radius: 12px; background: #f8fafc; padding: 14px 16px; }
:global(.result-card-head) { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
:global(.result-card h5) { margin: 0 0 6px; font-size: 14px; }
:global(.result-card p), :global(.result-card small) { margin: 0; color: #64748b; font-size: 12px; line-height: 1.6; }
:global(.info-list) { display: grid; gap: 10px; }
:global(.info-item) { border: 1px solid #e5e7eb; border-radius: 10px; background: #f8fafc; padding: 12px 14px; }
:global(.info-item span) { display: block; margin-bottom: 4px; color: #64748b; font-size: 11px; }
:global(.info-item strong) { color: #0f172a; }
:global(.inline-form) { display: flex; gap: 10px; align-items: center; margin-top: 14px; }
:global(.inline-form input) { flex: 1; }
:global(.table-wrap) { overflow: auto; }
:global(.task-table) { width: 100%; border-collapse: collapse; font-size: 12px; }
:global(.task-table th), :global(.task-table td) { padding: 10px 12px; border-bottom: 1px solid #e5e7eb; text-align: left; }
:global(.task-table th) { background: #f8fafc; color: #64748b; font-weight: 700; }
:global(.task-detail) { background: #f8fafc; border: 1px solid #e5e7eb; border-radius: 12px; padding: 16px; }
:global(.task-detail-head) { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
:global(.task-detail h5) { margin: 0 0 10px; font-size: 14px; }
:global(.code-block) { margin: 0; max-height: 240px; overflow: auto; border-radius: 10px; padding: 14px; background: #0f172a; color: #e2e8f0; font-size: 12px; line-height: 1.6; }
:global(.error-block) { background: #450a0a; color: #fecaca; }
:global(hr) { border: none; border-top: 1px solid #e5e7eb; margin: 18px 0; }

/* ── 认证页 ── */
:global(.auth-shell) { min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 24px; background: radial-gradient(circle at top left, rgba(37,99,235,0.12), transparent 22%), linear-gradient(180deg, #eff6ff 0%, #f8fafc 100%); }
:global(.auth-card) { width: min(400px, 100%); background: #fff; border: 1px solid #e5e7eb; border-radius: 20px; box-shadow: 0 24px 60px rgba(15,23,42,0.08); padding: 28px; }
:global(.auth-brand) { display: flex; align-items: center; gap: 14px; margin-bottom: 24px; }
:global(.brand-mark) { width: 48px; height: 48px; display: inline-flex; align-items: center; justify-content: center; border-radius: 14px; background: #0f172a; color: #fff; font-weight: 700; }
:global(.auth-brand h1) { margin: 0 0 4px; font-size: 26px; }
:global(.auth-brand p) { margin: 0; color: #64748b; font-size: 14px; }
:global(.auth-switch) { display: inline-flex; width: 100%; padding: 4px; border-radius: 12px; background: #f1f5f9; margin-bottom: 20px; }
:global(.auth-tab) { flex: 1; height: 40px; border: none; border-radius: 10px; background: transparent; color: #475569; font-size: 14px; font-weight: 600; cursor: pointer; }
:global(.auth-tab.active) { background: #fff; color: #0f172a; box-shadow: 0 1px 2px rgba(15,23,42,0.08); }

/* ── 对话区 ── */
:global(.chat-area) { flex: 1; display: flex; flex-direction: column; max-width: 800px; width: 100%; margin: 0 auto; padding: 0 24px; height: calc(100vh - 0px); }
:global(.chat-messages) { flex: 1; overflow-y: auto; padding: 24px 0; }
:global(.msg-wrapper) { margin-bottom: 16px; max-width: 85%; }
:global(.msg-wrapper.user) { margin-left: auto; }
:global(.msg-wrapper.copilot) { margin-right: auto; }
:global(.msg-bubble) { padding: 12px 16px; border-radius: 16px; font-size: 14px; line-height: 1.7; }
:global(.user-bubble) { background: #2563eb; color: #fff; border-bottom-right-radius: 4px; }
:global(.copilot-bubble) { background: #fff; border: 1px solid #e5e7eb; border-bottom-left-radius: 4px; }
:global(.btn-toggle-detail) { margin-left: auto; font-size: 11px; color: #64748b; background: #f1f5f9; border: 1px solid #e5e7eb; border-radius: 6px; padding: 2px 10px; cursor: pointer; }
:global(.btn-toggle-detail:hover) { background: #e2e8f0; }
:global(.step-summary-inline) { font-size: 11px; color: #64748b; margin-left: auto; }
:global(.msg-card) { background: #fff; border: 1px solid #e5e7eb; border-radius: 14px; padding: 16px; width: 100%; }
:global(.msg-card-title) { font-weight: 700; margin-bottom: 10px; font-size: 14px; }
:global(.step-block) { margin-bottom: 10px; }
:global(.step-row) { display: flex; align-items: center; gap: 8px; padding: 6px 0; }
:global(.step-icon) { width: 20px; }
:global(.step-label) { flex: 1; font-size: 13px; }
:global(.step-detail) { margin-top: 8px; padding: 12px 14px; background: #f8fafc; border-radius: 10px; border: 1px solid #e5e7eb; }
:global(.match-score-big) { font-size: 32px; font-weight: 800; color: #2563eb; text-align: center; padding: 12px 0; }
:global(.match-score-big span) { font-size: 16px; font-weight: 600; color: #64748b; }
:global(.detail-item) { margin-top: 10px; }
:global(.detail-item h6) { margin: 0 0 6px; font-size: 13px; color: #334155; }
:global(.detail-item ul) { margin: 0; padding-left: 18px; font-size: 13px; line-height: 1.8; color: #334155; }
:global(.detail-text) { font-size: 13px; color: #334155; line-height: 1.7; }
:global(.tag-list) { display: flex; flex-wrap: wrap; gap: 6px; }
:global(.tag) { display: inline-block; padding: 2px 10px; background: #eff6ff; color: #2563eb; border-radius: 8px; font-size: 12px; font-weight: 600; }
:global(.question-item) { margin-top: 10px; padding: 10px 12px; background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; }
:global(.question-item strong) { display: block; font-size: 13px; color: #0f172a; margin-bottom: 4px; }
:global(.question-item small) { display: block; color: #64748b; font-size: 12px; line-height: 1.6; margin-top: 2px; }
:global(.question-item small em) { color: #94a3b8; font-style: normal; margin-right: 4px; }
:global(.result-sections) { display: flex; flex-direction: column; gap: 16px; }
:global(.result-sections .step-detail) { margin-top: 0; }
:global(.generated-resume-text) { font-size: 13px; line-height: 1.8; color: #334155; max-height: 500px; overflow: auto; padding: 12px; background: #f8fafc; border-radius: 8px; border: 1px solid #e5e7eb; }
:global(.error-block) { background: #fef2f2; color: #dc2626; border: 1px solid #fecaca; }
:global(.msg-final) { margin-top: 12px; padding-top: 10px; border-top: 1px solid #e5e7eb; }
:global(.msg-final p) { margin: 0 0 6px; font-size: 14px; }
:global(.msg-error) { color: #b91c1c; font-size: 13px; margin-top: 6px; }
:global(.msg-text) { white-space: pre-wrap; }
:global(.typing .dots::after) { content: "..."; animation: dots 1.5s steps(4, end) infinite; }
@keyframes dots { 0%, 20% { content: ""; } 40% { content: "."; } 60% { content: ".."; } 80%, 100% { content: "..."; } }
:global(.chat-input-bar) { padding: 16px 0; border-top: 1px solid #e5e7eb; background: #f8fafc; }
:global(.quick-actions) { display: flex; gap: 8px; margin-bottom: 10px; }
:global(.input-row) { display: flex; gap: 10px; }
:global(.chat-input) { flex: 1; height: 44px; border: 1px solid #cbd5e1; border-radius: 22px; padding: 0 18px; font-size: 14px; outline: none; background: #fff; }
:global(.chat-input:focus) { border-color: #2563eb; box-shadow: 0 0 0 3px rgba(37,99,235,0.1); }
:global(.chat-input:disabled) { background: #f1f5f9; }

/* ── 响应式 ── */
@media (max-width: 900px) { .sidebar { width: 200px; } .main-shell { margin-left: 200px; width: calc(100% - 200px); } :global(.chat-area) { padding: 0 16px; } :global(.msg-wrapper) { max-width: 92%; } }
@media (max-width: 720px) { .sidebar { width: 180px; } .main-shell { margin-left: 180px; width: calc(100% - 180px); } .grid { grid-template-columns: 1fr; } :global(.quick-actions) { flex-wrap: wrap; } }
</style>
