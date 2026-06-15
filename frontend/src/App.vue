<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from "vue";
import axios from "axios";
import {
  agentApi,
  authApi,
  jobApi,
  knowledgeApi,
  resumeApi,
  setUnauthorizedHandler,
  taskApi
} from "./api";

const menuItems = [
  { key: "overview", label: "概览" },
  { key: "resume", label: "简历管理" },
  { key: "job", label: "岗位管理" },
  { key: "analysis", label: "AI 分析" },
  { key: "knowledge", label: "RAG 知识库" },
  { key: "recommend", label: "岗位推荐" },
  { key: "task", label: "任务记录" }
];

const sectionMeta = {
  overview: {
    title: "概览",
    description: "查看当前用户、已选简历、已选岗位和系统能力总览。"
  },
  resume: {
    title: "简历管理",
    description: "上传简历、查看当前用户简历列表，并按用户内编号查询。"
  },
  job: {
    title: "岗位管理",
    description: "保存岗位 JD、查看岗位列表，并按用户内编号查询。"
  },
  analysis: {
    title: "AI 分析",
    description: "围绕当前简历和岗位执行匹配分析、简历优化和面试题生成。"
  },
  knowledge: {
    title: "RAG 知识库",
    description: "构建知识库并检索命中的知识片段。"
  },
  recommend: {
    title: "岗位推荐",
    description: "根据当前简历，从当前用户的岗位库中筛选最匹配的岗位。"
  },
  task: {
    title: "任务记录",
    description: "查看任务列表、任务输出和错误信息。"
  }
};

const token = ref(localStorage.getItem("token") || "");
const currentUser = ref(null);
const activeMenu = ref("overview");
const message = ref("请先登录。");
const error = ref("");

const currentResume = reactive({
  id: null,
  localId: null,
  fileName: "",
  contentPreview: "",
  content: ""
});

const currentJob = reactive({
  id: null,
  localId: null,
  company: "",
  title: "",
  jdText: ""
});

const loadingMap = reactive({
  auth: false,
  restore: false,
  resumeUpload: false,
  resumeList: false,
  resumeDetail: false,
  jobCreate: false,
  jobList: false,
  jobDetail: false,
  analyze: false,
  optimize: false,
  interview: false,
  knowledgeBuild: false,
  knowledgeSearch: false,
  recommend: false,
  tasks: false,
  taskDetail: false
});

const authMode = ref("login");
const authForm = reactive({
  username: "",
  password: ""
});

const resumeState = reactive({
  selectedFile: null,
  list: [],
  detailInput: "",
  detailResult: null
});

const jobState = reactive({
  form: {
    company: "",
    title: "",
    jd_text: ""
  },
  list: [],
  detailInput: "",
  detailResult: null
});

const analysisState = reactive({
  enableRag: true,
  analyzeResponse: null,
  optimizeResponse: null,
  interviewResponse: null
});

const knowledgeState = reactive({
  buildResult: null,
  searchQuery: "",
  topK: 5,
  searchResult: null
});

const recommendState = reactive({
  topK: 5,
  maxJobs: 10,
  result: null
});

const taskState = reactive({
  filterTaskType: "",
  items: [],
  selectedTask: null
});

const isLoggedIn = computed(() => Boolean(token.value && currentUser.value));
const currentSection = computed(() => sectionMeta[activeMenu.value] || sectionMeta.overview);
const currentAnalysis = computed(() => analysisState.analyzeResponse?.analysis || null);
const currentOptimization = computed(() => analysisState.optimizeResponse?.optimization || null);
const currentQuestions = computed(() => analysisState.interviewResponse?.questions || null);

function setMessage(text, isError = false) {
  if (isError) {
    error.value = text;
    message.value = "";
    return;
  }
  message.value = text;
  error.value = "";
}

function getErrorMessage(err) {
  if (axios.isAxiosError(err)) {
    return err.response?.data?.detail || err.message || "请求失败";
  }
  return err?.message || "请求失败";
}

function setLoading(key, value) {
  loadingMap[key] = value;
}

function resetCurrentResume() {
  currentResume.id = null;
  currentResume.localId = null;
  currentResume.fileName = "";
  currentResume.contentPreview = "";
  currentResume.content = "";
}

function resetCurrentJob() {
  currentJob.id = null;
  currentJob.localId = null;
  currentJob.company = "";
  currentJob.title = "";
  currentJob.jdText = "";
}

function resetAppData() {
  activeMenu.value = "overview";
  resetCurrentResume();
  resetCurrentJob();
  resumeState.selectedFile = null;
  resumeState.list = [];
  resumeState.detailInput = "";
  resumeState.detailResult = null;
  jobState.form.company = "";
  jobState.form.title = "";
  jobState.form.jd_text = "";
  jobState.list = [];
  jobState.detailInput = "";
  jobState.detailResult = null;
  analysisState.enableRag = true;
  analysisState.analyzeResponse = null;
  analysisState.optimizeResponse = null;
  analysisState.interviewResponse = null;
  knowledgeState.buildResult = null;
  knowledgeState.searchQuery = "";
  knowledgeState.topK = 5;
  knowledgeState.searchResult = null;
  recommendState.topK = 5;
  recommendState.maxJobs = 10;
  recommendState.result = null;
  taskState.filterTaskType = "";
  taskState.items = [];
  taskState.selectedTask = null;
}

function clearSession(notify = true) {
  localStorage.removeItem("token");
  token.value = "";
  currentUser.value = null;
  resetAppData();
  if (notify) {
    setMessage("登录状态已失效，请重新登录。", true);
  }
}

function onResumeFileChange(event) {
  const [file] = event.target.files || [];
  resumeState.selectedFile = file || null;
}

function applyResumeSelection(resume) {
  if (!resume) {
    return;
  }
  currentResume.id = resume.id ?? resume.resume_id ?? null;
  currentResume.localId = resume.local_resume_id ?? null;
  currentResume.fileName = resume.file_name || "";
  currentResume.contentPreview =
    resume.content_preview || String(resume.content || "").slice(0, 200);
  currentResume.content = resume.content || "";
}

function applyJobSelection(job) {
  if (!job) {
    return;
  }
  currentJob.id = job.id ?? job.job_id ?? null;
  currentJob.localId = job.local_job_id ?? null;
  currentJob.company = job.company || "";
  currentJob.title = job.title || "";
  currentJob.jdText = job.jd_text || job.jd_preview || "";
}

function normalizeToArray(value) {
  if (Array.isArray(value)) {
    return value.filter(Boolean);
  }
  if (typeof value === "string" && value.trim()) {
    return [value.trim()];
  }
  return [];
}

function formatJson(value) {
  if (value === undefined || value === null || value === "") {
    return "暂无内容";
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function findFirstValue(source, keys) {
  if (!source || typeof source !== "object") {
    return null;
  }
  for (const key of keys) {
    const value = source[key];
    if (value !== undefined && value !== null && value !== "") {
      return value;
    }
  }
  return null;
}

function getMatchScore(source) {
  const raw = findFirstValue(source, ["match_score", "score"]);
  if (raw === null) {
    return 0;
  }
  const matched = String(raw).match(/\d+/);
  const score = matched ? Number(matched[0]) : Number(raw);
  if (Number.isNaN(score)) {
    return 0;
  }
  return Math.max(0, Math.min(100, score));
}

function getInterviewGroups() {
  const result = currentQuestions.value;
  if (!result || typeof result !== "object") {
    return [];
  }

  const groups = [
    { key: "technical_questions", label: "技术问题" },
    { key: "project_questions", label: "项目问题" },
    { key: "behavior_questions", label: "行为问题" },
    { key: "risk_questions", label: "风险问题" }
  ];

  return groups
    .map((group) => ({
      ...group,
      items: normalizeToArray(result[group.key]).map((item) => {
        if (item && typeof item === "object") {
          return {
            question: item.question || item.title || "未命名问题",
            whyAsk: item.why_ask || item.reason || "",
            answerHint: item.answer_hint || item.hint || ""
          };
        }
        return {
          question: String(item),
          whyAsk: "",
          answerHint: ""
        };
      })
    }))
    .filter((group) => group.items.length > 0);
}

function ensureResumeAndJob() {
  if (!currentResume.id) {
    setMessage("请先选择当前简历。", true);
    return false;
  }
  if (!currentJob.id) {
    setMessage("请先选择当前岗位。", true);
    return false;
  }
  return true;
}

async function fetchResumeList() {
  if (!isLoggedIn.value) {
    return;
  }
  setLoading("resumeList", true);
  try {
    const response = await resumeApi.listResumes();
    resumeState.list = response.items || [];
  } catch (err) {
    setMessage(getErrorMessage(err), true);
  } finally {
    setLoading("resumeList", false);
  }
}

async function fetchJobList() {
  if (!isLoggedIn.value) {
    return;
  }
  setLoading("jobList", true);
  try {
    const response = await jobApi.listJobs();
    jobState.list = response.items || [];
  } catch (err) {
    setMessage(getErrorMessage(err), true);
  } finally {
    setLoading("jobList", false);
  }
}

async function fetchTasks() {
  if (!isLoggedIn.value) {
    return;
  }
  setLoading("tasks", true);
  try {
    const params = {};
    if (taskState.filterTaskType.trim()) {
      params.task_type = taskState.filterTaskType.trim();
    }
    const response = await taskApi.listTasks(params);
    taskState.items = response.items || [];
  } catch (err) {
    setMessage(getErrorMessage(err), true);
  } finally {
    setLoading("tasks", false);
  }
}

async function fetchTaskDetail(taskId) {
  setLoading("taskDetail", true);
  try {
    taskState.selectedTask = await taskApi.getTask(taskId);
  } catch (err) {
    setMessage(getErrorMessage(err), true);
  } finally {
    setLoading("taskDetail", false);
  }
}

async function restoreSession() {
  if (!token.value) {
    return;
  }
  setLoading("restore", true);
  try {
    const user = await authApi.getCurrentUser();
    currentUser.value = user;
    setMessage(`欢迎回来，${user.username}。`);
    await Promise.all([fetchResumeList(), fetchJobList(), fetchTasks()]);
  } catch (err) {
    clearSession(false);
    setMessage(getErrorMessage(err), true);
  } finally {
    setLoading("restore", false);
  }
}

async function submitAuth() {
  if (!authForm.username || !authForm.password) {
    setMessage("请输入用户名和密码。", true);
    return;
  }

  setLoading("auth", true);
  try {
    const response =
      authMode.value === "register"
        ? await authApi.register(authForm.username, authForm.password)
        : await authApi.login(authForm.username, authForm.password);
    token.value = response.access_token;
    localStorage.setItem("token", response.access_token);
    currentUser.value = {
      id: response.user_id,
      username: response.username
    };
    authForm.username = "";
    authForm.password = "";
    setMessage(authMode.value === "register" ? "注册成功，已自动登录。" : "登录成功。");
    await Promise.all([fetchResumeList(), fetchJobList(), fetchTasks()]);
  } catch (err) {
    setMessage(getErrorMessage(err), true);
  } finally {
    setLoading("auth", false);
  }
}

function logout() {
  clearSession(false);
  setMessage("已退出登录。");
}

async function uploadResume() {
  if (!resumeState.selectedFile) {
    setMessage("请先选择简历文件。", true);
    return;
  }
  setLoading("resumeUpload", true);
  try {
    const response = await resumeApi.uploadResume(resumeState.selectedFile);
    applyResumeSelection({
      id: response.resume_id,
      local_resume_id: response.local_resume_id,
      file_name: response.file_name,
      content_preview: response.content_preview
    });
    await fetchResumeList();
    setMessage(`简历上传成功，第 ${response.local_resume_id} 份简历。`);
  } catch (err) {
    setMessage(getErrorMessage(err), true);
  } finally {
    setLoading("resumeUpload", false);
  }
}

async function fetchResumeDetail() {
  if (!resumeState.detailInput) {
    setMessage("请输入本地简历编号。", true);
    return;
  }
  setLoading("resumeDetail", true);
  try {
    const response = await resumeApi.getResumeByLocalId(Number(resumeState.detailInput));
    resumeState.detailResult = response;
    applyResumeSelection(response);
    setMessage(`已加载第 ${response.local_resume_id} 份简历。`);
  } catch (err) {
    setMessage(getErrorMessage(err), true);
  } finally {
    setLoading("resumeDetail", false);
  }
}

async function saveJob() {
  if (!jobState.form.title || !jobState.form.jd_text) {
    setMessage("请填写岗位名称和岗位 JD。", true);
    return;
  }
  setLoading("jobCreate", true);
  try {
    const response = await jobApi.createJob({
      company: jobState.form.company || null,
      title: jobState.form.title,
      jd_text: jobState.form.jd_text
    });
    applyJobSelection({
      id: response.job_id,
      local_job_id: response.local_job_id,
      company: jobState.form.company,
      title: jobState.form.title,
      jd_text: jobState.form.jd_text
    });
    await fetchJobList();
    setMessage(`岗位保存成功，第 ${response.local_job_id} 个岗位。`);
  } catch (err) {
    setMessage(getErrorMessage(err), true);
  } finally {
    setLoading("jobCreate", false);
  }
}

async function fetchJobDetail() {
  if (!jobState.detailInput) {
    setMessage("请输入本地岗位编号。", true);
    return;
  }
  setLoading("jobDetail", true);
  try {
    const response = await jobApi.getJobByLocalId(Number(jobState.detailInput));
    jobState.detailResult = response;
    applyJobSelection(response);
    setMessage(`已加载第 ${response.local_job_id} 个岗位。`);
  } catch (err) {
    setMessage(getErrorMessage(err), true);
  } finally {
    setLoading("jobDetail", false);
  }
}

async function runAnalyze() {
  if (!ensureResumeAndJob()) {
    return;
  }
  setLoading("analyze", true);
  try {
    analysisState.analyzeResponse = await agentApi.analyze({
      resume_id: Number(currentResume.id),
      job_id: Number(currentJob.id)
    });
    setMessage("岗位匹配分析完成。");
    await fetchTasks();
  } catch (err) {
    setMessage(getErrorMessage(err), true);
  } finally {
    setLoading("analyze", false);
  }
}

async function runOptimizeResume() {
  if (!ensureResumeAndJob()) {
    return;
  }
  setLoading("optimize", true);
  try {
    analysisState.optimizeResponse = await agentApi.optimizeResume({
      resume_id: Number(currentResume.id),
      job_id: Number(currentJob.id)
    });
    setMessage("简历优化建议生成完成。");
    await fetchTasks();
  } catch (err) {
    setMessage(getErrorMessage(err), true);
  } finally {
    setLoading("optimize", false);
  }
}

async function runInterviewQuestions() {
  if (!ensureResumeAndJob()) {
    return;
  }
  setLoading("interview", true);
  try {
    analysisState.interviewResponse = await agentApi.generateInterviewQuestions({
      resume_id: Number(currentResume.id),
      job_id: Number(currentJob.id),
      enable_rag: analysisState.enableRag
    });
    setMessage("面试题生成完成。");
    await fetchTasks();
  } catch (err) {
    setMessage(getErrorMessage(err), true);
  } finally {
    setLoading("interview", false);
  }
}

async function buildKnowledge() {
  setLoading("knowledgeBuild", true);
  try {
    knowledgeState.buildResult = await knowledgeApi.buildKnowledge();
    setMessage("知识库构建完成。");
  } catch (err) {
    setMessage(getErrorMessage(err), true);
  } finally {
    setLoading("knowledgeBuild", false);
  }
}

async function searchKnowledge() {
  if (!knowledgeState.searchQuery.trim()) {
    setMessage("请输入检索内容。", true);
    return;
  }
  setLoading("knowledgeSearch", true);
  try {
    knowledgeState.searchResult = await knowledgeApi.searchKnowledge(
      knowledgeState.searchQuery.trim(),
      Number(knowledgeState.topK) || 5
    );
    setMessage("知识检索完成。");
  } catch (err) {
    setMessage(getErrorMessage(err), true);
  } finally {
    setLoading("knowledgeSearch", false);
  }
}

async function runRecommendJobs() {
  if (!currentResume.id) {
    setMessage("请先选择当前简历。", true);
    return;
  }
  setLoading("recommend", true);
  try {
    recommendState.result = await agentApi.recommendJobs({
      resume_id: Number(currentResume.id),
      top_k: Number(recommendState.topK) || 5,
      max_jobs: Number(recommendState.maxJobs) || 10
    });
    setMessage(
      recommendState.result.items?.length ? "岗位推荐完成。" : "暂无推荐结果。"
    );
    await fetchTasks();
  } catch (err) {
    setMessage(getErrorMessage(err), true);
  } finally {
    setLoading("recommend", false);
  }
}

onMounted(() => {
  setUnauthorizedHandler(() => clearSession());
  restoreSession();
});

onUnmounted(() => {
  setUnauthorizedHandler(null);
});
</script>

<template>
  <div class="root-app">
    <template v-if="!isLoggedIn">
      <div class="auth-shell">
        <div class="auth-card">
          <div class="auth-brand">
            <div class="brand-mark">JA</div>
            <div>
              <h1>JobAgent</h1>
              <p>AI 求职助手</p>
            </div>
          </div>

          <div class="auth-switch">
            <button class="auth-tab" :class="{ active: authMode === 'login' }" @click="authMode = 'login'">
              登录
            </button>
            <button class="auth-tab" :class="{ active: authMode === 'register' }" @click="authMode = 'register'">
              注册
            </button>
          </div>

          <div class="form-stack">
            <label class="field">
              <span>用户名</span>
              <input v-model="authForm.username" type="text" placeholder="请输入用户名" />
            </label>
            <label class="field">
              <span>密码</span>
              <input v-model="authForm.password" type="password" placeholder="请输入密码" @keyup.enter="submitAuth" />
            </label>
          </div>

          <div v-if="error" class="alert alert-error">{{ error }}</div>
          <div v-else-if="message" class="alert alert-info">{{ message }}</div>

          <button class="btn btn-primary btn-block" :disabled="loadingMap.auth" @click="submitAuth">
            {{ loadingMap.auth ? "处理中..." : authMode === "login" ? "登录" : "注册并进入" }}
          </button>
        </div>
      </div>
    </template>

    <template v-else>
      <div class="app-shell">
        <aside class="sidebar">
          <div class="sidebar-brand">
            <div class="sidebar-logo">JA</div>
            <div>
              <strong>JobAgent</strong>
              <p>AI 求职助手</p>
            </div>
          </div>

          <nav class="sidebar-nav">
            <button
              v-for="item in menuItems"
              :key="item.key"
              class="nav-item"
              :class="{ active: activeMenu === item.key }"
              @click="activeMenu = item.key"
            >
              {{ item.label }}
            </button>
          </nav>

          <div class="sidebar-panel">
            <span>当前简历</span>
            <strong>{{ currentResume.localId ? `第 ${currentResume.localId} 份` : "未选择" }}</strong>
            <small v-if="currentResume.id">系统 ID：{{ currentResume.id }}</small>
          </div>

          <div class="sidebar-panel">
            <span>当前岗位</span>
            <strong>{{ currentJob.localId ? `第 ${currentJob.localId} 个` : "未选择" }}</strong>
            <small v-if="currentJob.id">系统 ID：{{ currentJob.id }}</small>
          </div>
        </aside>

        <div class="main-shell">
          <header class="topbar">
            <div>
              <p class="eyebrow">JobAgent Dashboard</p>
              <h2>{{ currentSection.title }}</h2>
            </div>
            <div class="topbar-user">
              <div class="user-chip">
                <span>当前用户</span>
                <strong>{{ currentUser?.username }}</strong>
              </div>
              <button class="btn btn-secondary" @click="logout">退出登录</button>
            </div>
          </header>

          <main class="page-content">
            <section class="page-header">
              <h3>{{ currentSection.title }}</h3>
              <p>{{ currentSection.description }}</p>
            </section>

            <div v-if="error" class="alert alert-error">{{ error }}</div>
            <div v-else-if="message" class="alert alert-success">{{ message }}</div>

            <template v-if="activeMenu === 'overview'">
              <section class="card hero-card">
                <h4>欢迎回来，{{ currentUser?.username }}</h4>
                <p>当前前端优先展示用户内编号，系统内部仍保留全局 ID 做唯一关联。</p>
              </section>

              <section class="stats-grid">
                <article class="card stat-card">
                  <span>当前简历</span>
                  <strong>{{ currentResume.localId ? `第 ${currentResume.localId} 份` : "未选择" }}</strong>
                  <small v-if="currentResume.id">系统 ID：{{ currentResume.id }}</small>
                </article>
                <article class="card stat-card">
                  <span>当前岗位</span>
                  <strong>{{ currentJob.localId ? `第 ${currentJob.localId} 个` : "未选择" }}</strong>
                  <small v-if="currentJob.id">系统 ID：{{ currentJob.id }}</small>
                </article>
                <article class="card stat-card">
                  <span>当前用户</span>
                  <strong>{{ currentUser?.username || "-" }}</strong>
                </article>
              </section>
            </template>

            <template v-else-if="activeMenu === 'resume'">
              <section class="grid">
                <article class="card">
                  <div class="card-head">
                    <div>
                      <h4>上传简历</h4>
                      <p>上传后会自动分配当前用户内的简历编号。</p>
                    </div>
                  </div>
                  <div class="form-stack">
                    <label class="field">
                      <span>选择文件</span>
                      <input type="file" accept=".pdf,.docx,.txt" @change="onResumeFileChange" />
                    </label>
                    <button class="btn btn-primary" :disabled="loadingMap.resumeUpload" @click="uploadResume">
                      {{ loadingMap.resumeUpload ? "上传中..." : "上传简历" }}
                    </button>
                  </div>
                </article>

                <article class="card">
                  <div class="card-head">
                    <div>
                      <h4>当前简历</h4>
                      <p>优先显示本地编号，详情中仍保留系统 ID。</p>
                    </div>
                  </div>
                  <div v-if="currentResume.id" class="info-list">
                    <div class="info-item"><span>用户内编号</span><strong>第 {{ currentResume.localId }} 份</strong></div>
                    <div class="info-item"><span>系统 ID</span><strong>{{ currentResume.id }}</strong></div>
                    <div class="info-item"><span>文件名</span><strong>{{ currentResume.fileName || "-" }}</strong></div>
                    <div class="info-item"><span>内容预览</span><p>{{ currentResume.contentPreview || "暂无内容" }}</p></div>
                  </div>
                  <p v-else class="empty-state">还没有选中简历。</p>
                </article>
              </section>

              <section class="card section-card">
                <div class="card-head">
                  <div>
                    <h4>按本地编号查询</h4>
                    <p>输入当前用户的第几份简历，例如 1、2、3。</p>
                  </div>
                  <button class="btn btn-secondary" :disabled="loadingMap.resumeList" @click="fetchResumeList">
                    刷新列表
                  </button>
                </div>
                <div class="inline-form">
                  <input v-model="resumeState.detailInput" type="number" min="1" placeholder="请输入本地简历编号" />
                  <button class="btn btn-secondary" :disabled="loadingMap.resumeDetail" @click="fetchResumeDetail">
                    {{ loadingMap.resumeDetail ? "查询中..." : "查询简历" }}
                  </button>
                </div>

                <div v-if="resumeState.list.length" class="result-list section-top">
                  <article v-for="item in resumeState.list" :key="item.id" class="result-card">
                    <div class="result-card-head">
                      <div>
                        <h5>第 {{ item.local_resume_id }} 份简历</h5>
                        <p>{{ item.file_name }}</p>
                      </div>
                      <button class="btn btn-secondary btn-small" @click="applyResumeSelection(item)">设为当前</button>
                    </div>
                    <p>{{ item.content_preview || "暂无预览内容" }}</p>
                  </article>
                </div>
              </section>
            </template>

            <template v-else-if="activeMenu === 'job'">
              <section class="card">
                <div class="card-head">
                  <div>
                    <h4>保存岗位 JD</h4>
                    <p>保存后会自动分配当前用户内的岗位编号。</p>
                  </div>
                </div>
                <div class="grid form-grid">
                  <label class="field">
                    <span>公司名称</span>
                    <input v-model="jobState.form.company" type="text" placeholder="例如：某科技公司" />
                  </label>
                  <label class="field">
                    <span>岗位名称</span>
                    <input v-model="jobState.form.title" type="text" placeholder="例如：后端开发工程师" />
                  </label>
                </div>
                <label class="field">
                  <span>岗位 JD</span>
                  <textarea v-model="jobState.form.jd_text" placeholder="请输入岗位职责、技术要求和经验要求" />
                </label>
                <button class="btn btn-primary section-top" :disabled="loadingMap.jobCreate" @click="saveJob">
                  {{ loadingMap.jobCreate ? "保存中..." : "保存岗位" }}
                </button>
              </section>

              <section class="card section-card">
                <div class="card-head">
                  <div>
                    <h4>按本地编号查询</h4>
                    <p>输入当前用户的第几个岗位，例如 1、2、3。</p>
                  </div>
                  <button class="btn btn-secondary" :disabled="loadingMap.jobList" @click="fetchJobList">
                    刷新列表
                  </button>
                </div>
                <div class="inline-form">
                  <input v-model="jobState.detailInput" type="number" min="1" placeholder="请输入本地岗位编号" />
                  <button class="btn btn-secondary" :disabled="loadingMap.jobDetail" @click="fetchJobDetail">
                    {{ loadingMap.jobDetail ? "查询中..." : "查询岗位" }}
                  </button>
                </div>

                <div v-if="jobState.list.length" class="result-list section-top">
                  <article v-for="item in jobState.list" :key="item.id" class="result-card">
                    <div class="result-card-head">
                      <div>
                        <h5>第 {{ item.local_job_id }} 个岗位</h5>
                        <p>{{ item.company || "未知公司" }} / {{ item.title }}</p>
                      </div>
                      <button class="btn btn-secondary btn-small" @click="applyJobSelection(item)">设为当前</button>
                    </div>
                    <p>{{ item.jd_preview || "暂无内容" }}</p>
                  </article>
                </div>
              </section>
            </template>

            <template v-else-if="activeMenu === 'analysis'">
              <section class="status-bar">
                <div class="status-card">
                  <span>当前简历</span>
                  <strong>{{ currentResume.localId ? `第 ${currentResume.localId} 份` : "未选择" }}</strong>
                </div>
                <div class="status-card">
                  <span>当前岗位</span>
                  <strong>{{ currentJob.localId ? `第 ${currentJob.localId} 个` : "未选择" }}</strong>
                </div>
              </section>

              <section class="card">
                <div class="action-row">
                  <button class="btn btn-primary" :disabled="loadingMap.analyze" @click="runAnalyze">
                    {{ loadingMap.analyze ? "处理中..." : "岗位匹配分析" }}
                  </button>
                  <button class="btn btn-secondary" :disabled="loadingMap.optimize" @click="runOptimizeResume">
                    {{ loadingMap.optimize ? "处理中..." : "简历优化建议" }}
                  </button>
                  <button class="btn btn-secondary" :disabled="loadingMap.interview" @click="runInterviewQuestions">
                    {{ loadingMap.interview ? "处理中..." : "RAG 增强面试题" }}
                  </button>
                </div>
                <label class="toggle-line">
                  <input v-model="analysisState.enableRag" type="checkbox" />
                  <span>面试题生成时启用 RAG</span>
                </label>
              </section>

              <section class="grid section-card">
                <article class="card">
                  <div class="card-head">
                    <div>
                      <h4>岗位匹配结果</h4>
                      <p>展示匹配分数、优势、不足和建议。</p>
                    </div>
                    <div v-if="currentAnalysis" class="score-badge">{{ getMatchScore(currentAnalysis) }}</div>
                  </div>
                  <template v-if="currentAnalysis">
                    <div class="stack-block">
                      <h5>匹配原因</h5>
                      <p>{{ findFirstValue(currentAnalysis, ["match_reason", "summary"]) || "暂无匹配原因" }}</p>
                    </div>
                    <div class="stack-block">
                      <h5>优势</h5>
                      <ul class="list"><li v-for="item in normalizeToArray(currentAnalysis.advantages)" :key="item">{{ item }}</li></ul>
                    </div>
                    <div class="stack-block">
                      <h5>不足</h5>
                      <ul class="list"><li v-for="item in normalizeToArray(currentAnalysis.weaknesses)" :key="item">{{ item }}</li></ul>
                    </div>
                    <div class="stack-block">
                      <h5>建议</h5>
                      <ul class="list"><li v-for="item in normalizeToArray(currentAnalysis.suggestions)" :key="item">{{ item }}</li></ul>
                    </div>
                  </template>
                  <p v-else class="empty-state">执行岗位匹配分析后，这里会展示结果。</p>
                </article>

                <article class="card">
                  <div class="card-head">
                    <div>
                      <h4>简历优化建议</h4>
                      <p>展示摘要、技能关键词、项目建议和风险点。</p>
                    </div>
                  </div>
                  <template v-if="currentOptimization">
                    <div class="stack-block"><h5>摘要</h5><p>{{ currentOptimization.summary || "暂无摘要" }}</p></div>
                    <div class="stack-block"><h5>技能关键词</h5><ul class="list"><li v-for="item in normalizeToArray(currentOptimization.skill_keywords)" :key="item">{{ item }}</li></ul></div>
                    <div class="stack-block"><h5>项目建议</h5><ul class="list"><li v-for="item in normalizeToArray(currentOptimization.project_suggestions)" :key="item">{{ item }}</li></ul></div>
                    <div class="stack-block"><h5>改写建议</h5><ul class="list"><li v-for="item in normalizeToArray(currentOptimization.resume_rewrite_suggestions)" :key="item">{{ item }}</li></ul></div>
                    <div class="stack-block"><h5>风险点</h5><ul class="list"><li v-for="item in normalizeToArray(currentOptimization.risk_points)" :key="item">{{ item }}</li></ul></div>
                  </template>
                  <p v-else class="empty-state">执行简历优化后，这里会展示结果。</p>
                </article>
              </section>

              <section class="card section-card">
                <div class="card-head">
                  <div>
                    <h4>面试题结果</h4>
                    <p>按类型分组展示技术、项目、行为和风险问题。</p>
                  </div>
                </div>
                <div v-if="getInterviewGroups().length" class="question-grid">
                  <div v-for="group in getInterviewGroups()" :key="group.key" class="question-group">
                    <h5>{{ group.label }}</h5>
                    <article v-for="item in group.items" :key="item.question + item.whyAsk" class="question-card">
                      <strong>{{ item.question }}</strong>
                      <p v-if="item.whyAsk"><span>为什么问：</span>{{ item.whyAsk }}</p>
                      <p v-if="item.answerHint"><span>回答提示：</span>{{ item.answerHint }}</p>
                    </article>
                  </div>
                </div>
                <p v-else class="empty-state">执行面试题生成后，这里会展示结果。</p>
              </section>
            </template>

            <template v-else-if="activeMenu === 'knowledge'">
              <section class="grid">
                <article class="card">
                  <div class="card-head">
                    <div>
                      <h4>构建知识库</h4>
                      <p>调用后端构建接口并展示文件数和切片数。</p>
                    </div>
                  </div>
                  <button class="btn btn-primary" :disabled="loadingMap.knowledgeBuild" @click="buildKnowledge">
                    {{ loadingMap.knowledgeBuild ? "构建中..." : "构建知识库" }}
                  </button>
                  <div v-if="knowledgeState.buildResult" class="info-list section-top">
                    <div class="info-item"><span>success</span><strong>{{ knowledgeState.buildResult.success }}</strong></div>
                    <div class="info-item"><span>file_count</span><strong>{{ knowledgeState.buildResult.file_count }}</strong></div>
                    <div class="info-item"><span>chunk_count</span><strong>{{ knowledgeState.buildResult.chunk_count }}</strong></div>
                  </div>
                </article>

                <article class="card">
                  <div class="card-head">
                    <div>
                      <h4>检索知识库</h4>
                      <p>输入 query 与 top_k，查看知识命中结果。</p>
                    </div>
                  </div>
                  <div class="form-stack">
                    <label class="field">
                      <span>Query</span>
                      <input v-model="knowledgeState.searchQuery" type="text" placeholder="例如：Spring Boot 微服务项目经验" />
                    </label>
                    <label class="field">
                      <span>Top K</span>
                      <input v-model="knowledgeState.topK" type="number" min="1" max="20" />
                    </label>
                    <button class="btn btn-secondary" :disabled="loadingMap.knowledgeSearch" @click="searchKnowledge">
                      {{ loadingMap.knowledgeSearch ? "检索中..." : "检索知识" }}
                    </button>
                  </div>
                </article>
              </section>

              <section class="card section-card">
                <div class="card-head">
                  <div>
                    <h4>检索结果</h4>
                    <p>展示命中的知识片段来源和内容。</p>
                  </div>
                </div>
                <div v-if="knowledgeState.searchResult?.items?.length" class="result-list">
                  <article v-for="(item, index) in knowledgeState.searchResult.items" :key="index" class="result-card">
                    <div class="result-card-head">
                      <div>
                        <h5>{{ item.title || "知识片段" }}</h5>
                        <p>{{ item.source || "未知来源" }}</p>
                      </div>
                      <span class="mini-badge">{{ item.score ?? "-" }}</span>
                    </div>
                    <p>{{ item.clean_content || item.content || "暂无内容" }}</p>
                  </article>
                </div>
                <p v-else class="empty-state">检索后，这里会展示命中的知识片段。</p>
              </section>
            </template>

            <template v-else-if="activeMenu === 'recommend'">
              <section class="card">
                <div class="card-head">
                  <div>
                    <h4>岗位推荐参数</h4>
                    <p>当前简历：{{ currentResume.localId ? `第 ${currentResume.localId} 份` : "未选择" }}</p>
                  </div>
                </div>
                <div class="grid form-grid">
                  <label class="field">
                    <span>Top K</span>
                    <input v-model="recommendState.topK" type="number" min="1" max="10" />
                  </label>
                  <label class="field">
                    <span>Max Jobs</span>
                    <input v-model="recommendState.maxJobs" type="number" min="1" max="20" />
                  </label>
                </div>
                <button class="btn btn-primary" :disabled="loadingMap.recommend" @click="runRecommendJobs">
                  {{ loadingMap.recommend ? "推荐中..." : "推荐岗位" }}
                </button>
              </section>

              <section class="card section-card">
                <div class="card-head">
                  <div>
                    <h4>推荐结果</h4>
                    <p>按匹配度展示最适合当前简历的岗位。</p>
                  </div>
                  <span class="mini-badge">{{ recommendState.result?.candidate_job_count ?? 0 }}</span>
                </div>
                <div v-if="recommendState.result?.items?.length" class="result-list">
                  <article v-for="item in recommendState.result.items" :key="item.job_id" class="recommend-card">
                    <div class="recommend-head">
                      <div>
                        <h5>{{ item.company || "未知公司" }}</h5>
                        <p>第 {{ item.local_job_id || "-" }} 个岗位 / {{ item.title || "未命名岗位" }}</p>
                      </div>
                      <div class="score-badge large">{{ getMatchScore(item) }}</div>
                    </div>
                    <div class="stack-block"><h5>匹配原因</h5><p>{{ item.match_reason || "暂无匹配原因" }}</p></div>
                    <div class="grid list-grid">
                      <div class="list-block"><h5>优势</h5><ul class="list"><li v-for="entry in normalizeToArray(item.advantages)" :key="entry">{{ entry }}</li></ul></div>
                      <div class="list-block"><h5>不足</h5><ul class="list"><li v-for="entry in normalizeToArray(item.weaknesses)" :key="entry">{{ entry }}</li></ul></div>
                    </div>
                    <div class="stack-block"><h5>建议</h5><ul class="list"><li v-for="entry in normalizeToArray(item.suggestions)" :key="entry">{{ entry }}</li></ul></div>
                  </article>
                </div>
                <p v-else class="empty-state">暂无推荐结果。</p>
              </section>
            </template>

            <template v-else-if="activeMenu === 'task'">
              <section class="card">
                <div class="card-head">
                  <div>
                    <h4>任务筛选</h4>
                    <p>支持按 task_type 过滤并查看任务详情。</p>
                  </div>
                </div>
                <div class="inline-form">
                  <input v-model="taskState.filterTaskType" type="text" placeholder="例如：MATCH_ANALYZE / JOB_RECOMMEND" />
                  <button class="btn btn-secondary" :disabled="loadingMap.tasks" @click="fetchTasks">
                    {{ loadingMap.tasks ? "刷新中..." : "刷新任务" }}
                  </button>
                </div>
              </section>

              <section class="grid task-layout section-card">
                <article class="card table-card">
                  <div class="table-wrap">
                    <table class="task-table">
                      <thead>
                        <tr>
                          <th>ID</th>
                          <th>类型</th>
                          <th>状态</th>
                          <th>resume_id</th>
                          <th>job_id</th>
                          <th>创建时间</th>
                          <th>更新时间</th>
                          <th>操作</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr v-for="task in taskState.items" :key="task.id">
                          <td>{{ task.id }}</td>
                          <td>{{ task.task_type || "-" }}</td>
                          <td>{{ task.status || "-" }}</td>
                          <td>{{ task.resume_id ?? "-" }}</td>
                          <td>{{ task.job_id ?? "-" }}</td>
                          <td>{{ task.created_at || "-" }}</td>
                          <td>{{ task.updated_at || "-" }}</td>
                          <td>
                            <button class="btn btn-secondary btn-small" :disabled="loadingMap.taskDetail" @click="fetchTaskDetail(task.id)">
                              查看详情
                            </button>
                          </td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </article>

                <article class="card">
                  <div class="card-head">
                    <div>
                      <h4>任务详情</h4>
                      <p>展示 output_json 与 error_msg。</p>
                    </div>
                  </div>
                  <template v-if="taskState.selectedTask">
                    <div class="info-list">
                      <div class="info-item"><span>task_id</span><strong>{{ taskState.selectedTask.id }}</strong></div>
                      <div class="info-item"><span>task_type</span><strong>{{ taskState.selectedTask.task_type || "-" }}</strong></div>
                      <div class="info-item"><span>status</span><strong>{{ taskState.selectedTask.status || "-" }}</strong></div>
                    </div>
                    <div class="stack-block">
                      <h5>output_json</h5>
                      <pre class="code-block">{{ formatJson(taskState.selectedTask.output_json) }}</pre>
                    </div>
                    <div class="stack-block">
                      <h5>error_msg</h5>
                      <pre class="code-block">{{ taskState.selectedTask.error_msg || "无错误信息" }}</pre>
                    </div>
                  </template>
                  <p v-else class="empty-state">点击左侧任务查看详情。</p>
                </article>
              </section>
            </template>
          </main>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
:global(html, body, #app) {
  margin: 0;
  min-height: 100%;
  background: #f8fafc;
  color: #0f172a;
  font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

:global(*) {
  box-sizing: border-box;
}

.root-app {
  min-height: 100vh;
}

.auth-shell {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background:
    radial-gradient(circle at top left, rgba(37, 99, 235, 0.12), transparent 22%),
    linear-gradient(180deg, #eff6ff 0%, #f8fafc 100%);
}

.auth-card {
  width: min(400px, 100%);
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 20px;
  box-shadow: 0 24px 60px rgba(15, 23, 42, 0.08);
  padding: 28px;
}

.auth-brand {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 24px;
}

.brand-mark {
  width: 48px;
  height: 48px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 14px;
  background: #0f172a;
  color: #ffffff;
  font-weight: 700;
}

.auth-brand h1 {
  margin: 0 0 4px;
  font-size: 26px;
}

.auth-brand p {
  margin: 0;
  color: #64748b;
  font-size: 14px;
}

.auth-switch {
  display: inline-flex;
  width: 100%;
  padding: 4px;
  border-radius: 12px;
  background: #f1f5f9;
  margin-bottom: 20px;
}

.auth-tab {
  flex: 1;
  height: 40px;
  border: none;
  border-radius: 10px;
  background: transparent;
  color: #475569;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}

.auth-tab.active {
  background: #ffffff;
  color: #0f172a;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.08);
}

.app-shell {
  min-height: 100vh;
  display: flex;
  background: #f8fafc;
}

.sidebar {
  position: fixed;
  left: 0;
  top: 0;
  bottom: 0;
  width: 248px;
  background: #0f172a;
  color: #cbd5e1;
  padding: 24px 16px;
  overflow-y: auto;
}

.sidebar-brand {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 28px;
  padding: 0 8px;
}

.sidebar-logo {
  width: 42px;
  height: 42px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 12px;
  background: #2563eb;
  color: #ffffff;
  font-weight: 700;
}

.sidebar-brand strong {
  display: block;
  color: #ffffff;
  font-size: 16px;
}

.sidebar-brand p {
  margin: 4px 0 0;
  color: #94a3b8;
  font-size: 12px;
}

.sidebar-nav {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.nav-item {
  height: 42px;
  width: 100%;
  padding: 0 14px;
  border: none;
  border-radius: 10px;
  background: transparent;
  color: #cbd5e1;
  text-align: left;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}

.nav-item:hover {
  background: #1e293b;
}

.nav-item.active {
  background: #2563eb;
  color: #ffffff;
}

.sidebar-panel {
  margin-top: 16px;
  padding: 14px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.06);
}

.sidebar-panel span,
.sidebar-panel small {
  display: block;
}

.sidebar-panel span {
  margin-bottom: 6px;
  color: #94a3b8;
  font-size: 12px;
}

.sidebar-panel strong {
  color: #ffffff;
  font-size: 16px;
}

.sidebar-panel small {
  margin-top: 6px;
  color: #94a3b8;
  font-size: 12px;
}

.main-shell {
  margin-left: 248px;
  width: calc(100% - 248px);
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

.topbar {
  height: 64px;
  background: #ffffff;
  border-bottom: 1px solid #e5e7eb;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 32px;
  position: sticky;
  top: 0;
  z-index: 10;
}

.eyebrow {
  margin: 0;
  color: #64748b;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.topbar h2 {
  margin: 2px 0 0;
  font-size: 22px;
}

.topbar-user {
  display: flex;
  align-items: center;
  gap: 12px;
}

.user-chip {
  padding: 8px 12px;
  border-radius: 12px;
  background: #ffffff;
  border: 1px solid #e5e7eb;
}

.user-chip span {
  display: block;
  color: #64748b;
  font-size: 12px;
}

.user-chip strong {
  display: block;
  color: #0f172a;
  font-size: 14px;
}

.page-content {
  padding: 32px;
  max-width: 1200px;
  width: 100%;
}

.page-header {
  margin-bottom: 20px;
}

.page-header h3 {
  margin: 0 0 8px;
  font-size: 28px;
}

.page-header p {
  margin: 0;
  color: #64748b;
  line-height: 1.7;
}

.card {
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 16px;
  padding: 24px;
  box-shadow: 0 10px 30px rgba(15, 23, 42, 0.04);
}

.hero-card {
  margin-bottom: 20px;
}

.hero-card h4 {
  margin: 0 0 10px;
  font-size: 28px;
}

.hero-card p,
.empty-state,
.card-head p,
.info-item p {
  margin: 0;
  color: #64748b;
  line-height: 1.7;
}

.stats-grid,
.grid,
.question-grid {
  display: grid;
  gap: 20px;
}

.stats-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.grid,
.question-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.stat-card span {
  display: block;
  margin-bottom: 8px;
  color: #64748b;
  font-size: 13px;
}

.stat-card strong {
  display: block;
  font-size: 24px;
  color: #0f172a;
}

.stat-card small {
  display: block;
  margin-top: 6px;
  color: #94a3b8;
}

.card-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}

.card-head h4 {
  margin: 0 0 8px;
  font-size: 18px;
}

.form-stack {
  display: grid;
  gap: 16px;
}

.form-grid {
  margin-bottom: 16px;
}

.field span {
  display: block;
  margin-bottom: 8px;
  color: #334155;
  font-size: 14px;
  font-weight: 600;
}

input,
textarea {
  width: 100%;
  border: 1px solid #cbd5e1;
  border-radius: 10px;
  padding: 10px 12px;
  font-size: 14px;
  outline: none;
}

input {
  height: 40px;
}

textarea {
  min-height: 160px;
  resize: vertical;
}

input:focus,
textarea:focus {
  border-color: #2563eb;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1);
}

.btn {
  border: none;
  border-radius: 10px;
  height: 40px;
  padding: 0 16px;
  font-weight: 600;
  font-size: 14px;
  cursor: pointer;
}

.btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-block {
  width: 100%;
}

.btn-primary {
  background: #2563eb;
  color: #ffffff;
}

.btn-secondary {
  background: #ffffff;
  color: #334155;
  border: 1px solid #cbd5e1;
}

.btn-small {
  height: 34px;
  padding: 0 12px;
  font-size: 13px;
}

.alert {
  border-radius: 12px;
  padding: 12px 14px;
  margin-bottom: 20px;
  font-size: 14px;
  line-height: 1.6;
}

.alert-success {
  background: #ecfdf5;
  color: #047857;
  border: 1px solid #a7f3d0;
}

.alert-error {
  background: #fef2f2;
  color: #b91c1c;
  border: 1px solid #fecaca;
}

.alert-info {
  background: #eff6ff;
  color: #1d4ed8;
  border: 1px solid #bfdbfe;
}

.inline-form,
.action-row,
.status-bar,
.topbar-user,
.result-card-head,
.recommend-head {
  display: flex;
  gap: 12px;
}

.inline-form {
  align-items: center;
}

.inline-form input {
  flex: 1;
}

.status-bar {
  margin-bottom: 20px;
}

.status-card {
  min-width: 180px;
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 14px;
  padding: 16px;
}

.status-card span {
  display: block;
  margin-bottom: 8px;
  color: #64748b;
  font-size: 12px;
}

.status-card strong {
  font-size: 18px;
}

.toggle-line {
  margin-top: 16px;
  display: inline-flex;
  align-items: center;
  gap: 10px;
}

.toggle-line input {
  width: 16px;
  height: 16px;
  margin: 0;
}

.info-list,
.result-list {
  display: grid;
  gap: 12px;
}

.info-item,
.result-card,
.recommend-card,
.question-card {
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  background: #f8fafc;
  padding: 14px 16px;
}

.info-item span {
  display: block;
  margin-bottom: 6px;
  color: #64748b;
  font-size: 12px;
}

.info-item strong {
  color: #0f172a;
}

.section-top {
  margin-top: 18px;
}

.section-card {
  margin-top: 20px;
}

.score-badge,
.mini-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  font-weight: 700;
}

.score-badge {
  min-width: 46px;
  height: 32px;
  padding: 0 12px;
  background: #dbeafe;
  color: #1d4ed8;
}

.score-badge.large {
  min-width: 60px;
  height: 40px;
  font-size: 18px;
}

.mini-badge {
  min-width: 36px;
  height: 28px;
  padding: 0 10px;
  background: #eff6ff;
  color: #2563eb;
}

.stack-block + .stack-block {
  margin-top: 16px;
}

.stack-block h5,
.question-group h5,
.result-card h5,
.recommend-card h5,
.list-block h5 {
  margin: 0 0 10px;
  font-size: 15px;
}

.stack-block p,
.result-card p,
.recommend-card p,
.question-card p {
  margin: 0;
  color: #334155;
  line-height: 1.7;
}

.list {
  margin: 0;
  padding-left: 18px;
  color: #334155;
  line-height: 1.7;
}

.list-grid {
  margin-top: 16px;
}

.question-group {
  display: grid;
  gap: 12px;
}

.question-card strong {
  display: block;
  margin-bottom: 8px;
}

.question-card span {
  color: #64748b;
  font-weight: 600;
  margin-right: 6px;
}

.recommend-head,
.result-card-head {
  justify-content: space-between;
  align-items: flex-start;
}

.task-layout {
  grid-template-columns: 1.2fr 0.8fr;
}

.table-card {
  padding: 0;
  overflow: hidden;
}

.table-wrap {
  overflow: auto;
}

.task-table {
  width: 100%;
  min-width: 840px;
  border-collapse: collapse;
}

.task-table th,
.task-table td {
  padding: 14px 16px;
  border-bottom: 1px solid #e5e7eb;
  text-align: left;
  font-size: 13px;
}

.task-table th {
  background: #f8fafc;
  color: #64748b;
  font-weight: 700;
}

.code-block {
  margin: 0;
  max-height: 260px;
  overflow: auto;
  border-radius: 12px;
  padding: 16px;
  background: #0f172a;
  color: #e2e8f0;
  font-size: 12px;
  line-height: 1.7;
}

@media (max-width: 900px) {
  .sidebar {
    width: 220px;
  }

  .main-shell {
    margin-left: 220px;
    width: calc(100% - 220px);
  }

  .page-content {
    padding: 24px;
  }

  .grid,
  .stats-grid,
  .question-grid,
  .task-layout {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .topbar {
    height: auto;
    padding: 18px 20px;
    align-items: flex-start;
    flex-direction: column;
  }

  .topbar-user,
  .inline-form,
  .action-row,
  .status-bar,
  .recommend-head,
  .result-card-head {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
