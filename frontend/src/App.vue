<script setup>
import { computed, onMounted, onUnmounted, provide, reactive, ref } from "vue";
import {
  adminApi,
  agentApi,
  authApi,
  copilotApi,
  evaluationApi,
  jobApi,
  knowledgeApi,
  resumeApi,
  setUnauthorizedHandler,
  taskApi,
} from "./api";
import { getErrorMessage } from "./shared/error.js";
import { useSelection } from "./composables/useSelection.js";
import { useSessions } from "./composables/useSessions.js";
import { useToast } from "./composables/useToast.js";
import AuthForm from "./components/AuthForm.vue";
import ChatPage from "./pages/ChatPage.vue";
import ResumePage from "./pages/ResumePage.vue";
import JobPage from "./pages/JobPage.vue";
import RecommendPage from "./pages/RecommendPage.vue";
import TaskPage from "./pages/TaskPage.vue";
import KnowledgePage from "./pages/KnowledgePage.vue";
import EvaluationPage from "./pages/EvaluationPage.vue";
import AdminDashboardPage from "./pages/admin/AdminDashboardPage.vue";
import AdminJobsPage from "./pages/admin/AdminJobsPage.vue";
import AdminResumesPage from "./pages/admin/AdminResumesPage.vue";
import AdminSessionsPage from "./pages/admin/AdminSessionsPage.vue";
import AdminTasksPage from "./pages/admin/AdminTasksPage.vue";
import AdminTracesPage from "./pages/admin/AdminTracesPage.vue";
import AdminUsersPage from "./pages/admin/AdminUsersPage.vue";

const baseSidebarItems = [
  { key: "chat", label: "对话", icon: "💬" },
  { key: "resume", label: "简历管理", icon: "📄" },
  { key: "job", label: "岗位管理", icon: "💼" },
  { key: "recommend", label: "岗位推荐", icon: "🎯" },
  { key: "task", label: "任务记录", icon: "🧾" },
];

const adminSidebarItems = [
  { key: "admin_dashboard", label: "管理仪表盘", icon: "📊" },
  { key: "admin_users", label: "用户管理", icon: "👤" },
  { key: "admin_resumes", label: "全局简历", icon: "📄" },
  { key: "admin_jobs", label: "全局岗位", icon: "💼" },
  { key: "admin_tasks", label: "全局任务", icon: "🧾" },
  { key: "admin_sessions", label: "全局会话", icon: "💬" },
  { key: "admin_traces", label: "链路追踪", icon: "🛰" },
  { key: "knowledge", label: "RAG 知识库", icon: "🗂️" },
  { key: "evaluation", label: "测评", icon: "📈" },
];

const token = ref(localStorage.getItem("token") || "");
const currentUser = ref(null);
const adminMode = ref(true);
const activeView = ref(null);
const isLoggedIn = computed(() => Boolean(token.value && currentUser.value));

const sidebarItems = computed(() => {
  if (currentUser.value?.is_admin) {
    return adminMode.value ? adminSidebarItems : baseSidebarItems;
  }
  return baseSidebarItems;
});

const { error, message, setMessage, toastVisible } = useToast();

const loadingMap = reactive({
  auth: false,
  restore: false,
  resumeUpload: false,
  resumeList: false,
  resumeDetail: false,
  jobCreate: false,
  jobList: false,
  jobDetail: false,
  knowledgeBuild: false,
  knowledgeSearch: false,
  recommend: false,
  tasks: false,
  taskDetail: false,
});

const chatRef = ref(null);
const resumeRef = ref(null);
const jobRef = ref(null);
const taskRef = ref(null);

const {
  applyJobSelection,
  applyResumeSelection,
  currentJob,
  currentResume,
  resetSelections,
} = useSelection(setMessage);

const {
  currentSessionId,
  deleteSession,
  loadSessions,
  newChat,
  selectSession,
  sessions,
  sessionsExpanded,
  storeSessionId,
  truncateGoal,
} = useSessions({
  activeView,
  adminMode,
  chatRef,
  copilotApi,
  currentUser,
  getErrorMessage,
  setMessage,
});

async function fetchResumeList() {
  if (!isLoggedIn.value || !resumeRef.value) return;
  loadingMap.resumeList = true;
  try {
    resumeRef.value.list = (await resumeApi.listResumes()).items || [];
  } catch (err) {
    setMessage(getErrorMessage(err), true);
  } finally {
    loadingMap.resumeList = false;
  }
}

async function fetchJobList() {
  if (!isLoggedIn.value || !jobRef.value) return;
  loadingMap.jobList = true;
  try {
    jobRef.value.list = (await jobApi.listJobs()).items || [];
  } catch (err) {
    setMessage(getErrorMessage(err), true);
  } finally {
    loadingMap.jobList = false;
  }
}

async function fetchTasks() {
  if (!isLoggedIn.value || !taskRef.value) return;
  loadingMap.tasks = true;
  try {
    await taskRef.value.fetchTasks();
  } catch (err) {
    setMessage(getErrorMessage(err), true);
  } finally {
    loadingMap.tasks = false;
  }
}

function clearSession(notify = true) {
  localStorage.removeItem("token");
  localStorage.removeItem("currentSessionId");
  token.value = "";
  currentUser.value = null;
  resetSelections();
  currentSessionId.value = null;
  sessions.value = [];
  if (notify) {
    setMessage("登录状态已失效，请重新登录。", true);
  }
}

async function restoreSession() {
  if (!token.value) return;
  loadingMap.restore = true;
  try {
    currentUser.value = await authApi.getCurrentUser();
    if (!currentUser.value?.is_admin) {
      adminMode.value = false;
    }
    if (!activeView.value) {
      activeView.value = currentUser.value?.is_admin ? "admin_dashboard" : "chat";
    }
    if (!currentUser.value?.is_admin || !adminMode.value) {
      chatRef.value?.welcome(currentUser.value?.username);
    }
    await Promise.all([fetchResumeList(), fetchJobList(), fetchTasks()]);
  } catch (err) {
    clearSession(false);
    setMessage(getErrorMessage(err), true);
  } finally {
    loadingMap.restore = false;
  }
}

function onLoggedIn() {
  if (!activeView.value) {
    activeView.value = currentUser.value?.is_admin ? "admin_dashboard" : "chat";
  }
  if (!currentUser.value?.is_admin) {
    adminMode.value = false;
  }
  chatRef.value?.welcome(currentUser.value?.username);
}

function logout() {
  clearSession(false);
  setMessage("已退出登录。");
}

function switchView(key) {
  activeView.value = key;
}

provide("api", { adminApi, agentApi, authApi, copilotApi, evaluationApi, jobApi, knowledgeApi, resumeApi, taskApi });
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

  if (currentSessionId.value) {
    const found = sessions.value.find((session) => session.id === currentSessionId.value);
    if (!found) {
      localStorage.removeItem("currentSessionId");
      currentSessionId.value = null;
    }
  }

  if (!currentSessionId.value && sessions.value.length > 0) {
    const recent = sessions.value.find((session) => session.status !== "ERROR") || sessions.value[0];
    if (recent) {
      await selectSession(recent.id);
    }
  }
});

onUnmounted(() => setUnauthorizedHandler(null));
</script>

<template>
  <div class="root-app">
    <template v-if="!isLoggedIn">
      <AuthForm @loggedIn="onLoggedIn" />
    </template>

    <template v-else>
      <div class="app-shell">
        <aside class="sidebar">
          <div class="sidebar-brand">
            <div class="sidebar-logo">JA</div>
            <div><strong>JobAgent</strong><p>AI Copilot</p></div>
          </div>

          <nav class="sidebar-nav">
            <button
              v-for="item in sidebarItems"
              :key="item.key"
              class="nav-item"
              :class="{ active: activeView === item.key }"
              @click="switchView(item.key)"
            >
              <span class="nav-icon">{{ item.icon }}</span>
              <span>{{ item.label }}</span>
            </button>

            <div v-if="!adminMode && sessions.length > 0" class="session-list">
              <div class="session-list-header" @click="sessionsExpanded = !sessionsExpanded">
                <span class="session-list-arrow">{{ sessionsExpanded ? "▼" : "▶" }}</span>
                <span>历史对话</span>
                <button class="btn-new-chat" title="新对话" @click.stop="newChat()">+</button>
              </div>
              <div v-show="sessionsExpanded" class="session-list-items">
                <button
                  v-for="session in sessions"
                  :key="session.id"
                  class="session-item"
                  :class="{ active: session.id === currentSessionId }"
                  @click="selectSession(session.id)"
                >
                  <span class="session-goal">{{ truncateGoal(session.goal) }}</span>
                  <span class="session-date">{{ (session.created_at || "").slice(0, 10) }}</span>
                  <span
                    class="session-delete"
                    title="删除此对话"
                    @click="deleteSession(session.id, $event)"
                  >✕</span>
                </button>
              </div>
            </div>
          </nav>

          <div v-if="!adminMode" class="sidebar-panel">
            <span>当前简历</span>
            <strong>{{ currentResume.localId ? `#${currentResume.localId}` : "未选择" }}</strong>
          </div>

          <div v-if="!adminMode" class="sidebar-panel">
            <span>当前岗位</span>
            <strong>{{ currentJob.localId ? `#${currentJob.localId}` : "未选择" }}</strong>
          </div>

          <div
            v-if="currentUser?.is_admin"
            class="sidebar-panel"
            style="cursor: pointer"
            @click="adminMode = !adminMode; activeView = adminMode ? 'admin_dashboard' : 'chat'"
          >
            <span style="font-size: 11px; color: #94a3b8">
              {{ adminMode ? "🧾 管理模式" : "💬 用户模式" }}
            </span>
            <strong style="font-size: 12px; color: #93c5fd">
              {{ adminMode ? "切换到 Copilot" : "返回管理后台" }}
            </strong>
          </div>

          <div class="sidebar-footer">
            <div class="user-chip-inline"><span>👤</span><strong>{{ currentUser?.username }}</strong></div>
            <button class="btn btn-secondary btn-small" @click="logout">退出</button>
          </div>
        </aside>

        <div class="main-shell">
          <ChatPage v-if="activeView === 'chat'" ref="chatRef" />
          <ResumePage v-if="activeView === 'resume'" ref="resumeRef" />
          <JobPage v-if="activeView === 'job'" ref="jobRef" />
          <RecommendPage v-if="activeView === 'recommend'" />
          <TaskPage v-if="activeView === 'task'" ref="taskRef" />
          <AdminDashboardPage v-if="activeView === 'admin_dashboard'" />
          <AdminUsersPage v-if="activeView === 'admin_users'" />
          <AdminResumesPage v-if="activeView === 'admin_resumes'" />
          <AdminJobsPage v-if="activeView === 'admin_jobs'" />
          <AdminTasksPage v-if="activeView === 'admin_tasks'" />
          <AdminSessionsPage v-if="activeView === 'admin_sessions'" />
          <AdminTracesPage v-if="activeView === 'admin_traces'" />
          <KnowledgePage v-if="activeView === 'knowledge'" />
          <EvaluationPage v-if="activeView === 'evaluation'" />
        </div>
      </div>
    </template>

    <Transition name="toast-fade">
      <div v-if="toastVisible && error" class="toast-overlay toast-overlay-error" @click="toastVisible = false">{{ error }}</div>
      <div v-else-if="toastVisible && message" class="toast-overlay toast-overlay-info" @click="toastVisible = false">{{ message }}</div>
    </Transition>
  </div>
</template>
