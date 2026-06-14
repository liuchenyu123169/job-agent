<script setup>
import { computed, ref } from "vue";
import axios from "axios";
import {
  analyzeMatch,
  createJob,
  generateInterviewQuestions,
  optimizeResume,
  uploadResume
} from "./api";

const selectedFile = ref(null);
const resumeInfo = ref(null);
const jobForm = ref({
  company: "",
  title: "",
  jd_text: ""
});
const jobInfo = ref(null);
const resultTitle = ref("");
const resultData = ref(null);
const statusMessage = ref("暂无结果，请先上传简历、保存岗位并点击 AI 操作按钮。");
const statusType = ref("info");

const uploadLoading = ref(false);
const jobLoading = ref(false);
const actionLoading = ref("");

const canRunAgent = computed(() => {
  return Boolean(resumeInfo.value?.resume_id && jobInfo.value?.job_id);
});

const hasResult = computed(() => resultData.value !== null);

function onFileChange(event) {
  const [file] = event.target.files || [];
  selectedFile.value = file || null;
}

function setStatus(type, message) {
  statusType.value = type;
  statusMessage.value = message;
}

function getErrorMessage(error) {
  if (axios.isAxiosError(error)) {
    return (
      error.response?.data?.detail ||
      error.message ||
      "请求失败，请检查后端服务是否启动"
    );
  }
  return error?.message || "请求失败，请检查后端服务是否启动";
}

function setResult(title, data) {
  resultTitle.value = title;
  resultData.value = data;
}

async function handleResumeUpload() {
  if (!selectedFile.value) {
    setStatus("error", "请先选择简历文件");
    return;
  }

  uploadLoading.value = true;
  setStatus("loading", "正在上传简历，请稍候...");

  try {
    resumeInfo.value = await uploadResume(selectedFile.value);
    setResult("简历上传结果", resumeInfo.value);
    setStatus(
      "success",
      `简历上传成功，resume_id = ${resumeInfo.value.resume_id}`
    );
  } catch (error) {
    setStatus("error", `上传失败：${getErrorMessage(error)}`);
  } finally {
    uploadLoading.value = false;
  }
}

async function handleJobSave() {
  if (!jobForm.value.title || !jobForm.value.jd_text) {
    setStatus("error", "请填写岗位名称和岗位 JD");
    return;
  }

  jobLoading.value = true;
  setStatus("loading", "正在保存岗位，请稍候...");

  try {
    jobInfo.value = await createJob(jobForm.value);
    setResult("岗位保存结果", jobInfo.value);
    setStatus("success", `岗位保存成功，job_id = ${jobInfo.value.job_id}`);
  } catch (error) {
    setStatus("error", `保存岗位失败：${getErrorMessage(error)}`);
  } finally {
    jobLoading.value = false;
  }
}

async function runAgentAction(actionType) {
  if (!resumeInfo.value?.resume_id) {
    setStatus("error", "请先上传简历");
    return;
  }

  if (!jobInfo.value?.job_id) {
    setStatus("error", "请先保存岗位 JD");
    return;
  }

  const actionMap = {
    analyze: {
      loadingText: "分析中...",
      statusText: "正在进行岗位匹配分析，请稍候...",
      title: "岗位匹配分析结果",
      successText: "岗位匹配分析完成",
      request: analyzeMatch
    },
    optimize: {
      loadingText: "优化中...",
      statusText: "正在生成简历优化建议，请稍候...",
      title: "简历优化建议结果",
      successText: "简历优化建议生成完成",
      request: optimizeResume
    },
    interview: {
      loadingText: "生成中...",
      statusText: "正在生成面试题，请稍候...",
      title: "面试题生成结果",
      successText: "面试题生成完成",
      request: generateInterviewQuestions
    }
  };

  const currentAction = actionMap[actionType];
  actionLoading.value = actionType;
  setStatus("loading", currentAction.statusText);

  try {
    const payload = {
      resume_id: resumeInfo.value.resume_id,
      job_id: jobInfo.value.job_id
    };
    const data = await currentAction.request(payload);
    setResult(currentAction.title, data);
    setStatus("success", currentAction.successText);
  } catch (error) {
    setStatus("error", `操作失败：${getErrorMessage(error)}`);
  } finally {
    actionLoading.value = "";
  }
}

function formatJson(value) {
  if (value === null) {
    return "暂无结果，请先上传简历、保存岗位并点击 AI 操作按钮。";
  }
  return JSON.stringify(value, null, 2);
}
</script>

<template>
  <main class="page">
    <section class="hero">
      <p class="eyebrow">JobAgent Demo</p>
      <h1>简历上传、岗位保存、AI 分析一页完成</h1>
      <p class="subtext">
        先上传简历，再保存岗位，然后执行岗位匹配分析、简历优化建议和面试题生成。
      </p>
    </section>

    <section class="status-banner" :class="statusType">
      {{ statusMessage }}
    </section>

    <section class="grid">
      <div class="panel">
        <h2>简历上传</h2>
        <input
          type="file"
          accept=".pdf,.docx,.txt"
          @change="onFileChange"
        />
        <button :disabled="uploadLoading || jobLoading || !!actionLoading" @click="handleResumeUpload">
          {{ uploadLoading ? "上传中..." : "上传简历" }}
        </button>

        <div v-if="resumeInfo" class="info">
          <p><strong>文件名：</strong>{{ resumeInfo.file_name }}</p>
          <p><strong>resume_id：</strong>{{ resumeInfo.resume_id }}</p>
          <p><strong>内容预览：</strong>{{ resumeInfo.content_preview }}</p>
        </div>
      </div>

      <div class="panel">
        <h2>岗位 JD</h2>
        <input v-model="jobForm.company" type="text" placeholder="公司名称（可选）" />
        <input v-model="jobForm.title" type="text" placeholder="岗位名称" />
        <textarea
          v-model="jobForm.jd_text"
          rows="8"
          placeholder="请输入岗位 JD"
        />
        <button :disabled="jobLoading || uploadLoading || !!actionLoading" @click="handleJobSave">
          {{ jobLoading ? "保存中..." : "保存岗位" }}
        </button>

        <div v-if="jobInfo" class="info">
          <p><strong>job_id：</strong>{{ jobInfo.job_id }}</p>
        </div>
      </div>
    </section>

    <section class="panel">
      <h2>AI 操作</h2>
      <div class="actions">
        <button
          :disabled="uploadLoading || jobLoading || !!actionLoading"
          @click="runAgentAction('analyze')"
        >
          {{ actionLoading === "analyze" ? "分析中..." : "岗位匹配分析" }}
        </button>
        <button
          :disabled="uploadLoading || jobLoading || !!actionLoading"
          @click="runAgentAction('optimize')"
        >
          {{ actionLoading === "optimize" ? "优化中..." : "简历优化建议" }}
        </button>
        <button
          :disabled="uploadLoading || jobLoading || !!actionLoading"
          @click="runAgentAction('interview')"
        >
          {{ actionLoading === "interview" ? "生成中..." : "生成面试题" }}
        </button>
      </div>
      <p class="hint">
        需要先拿到 `resume_id` 和 `job_id`，再执行 AI 接口。
      </p>
    </section>

    <section class="panel">
      <div class="result-header">
        <h2>结果展示</h2>
        <span v-if="hasResult" class="result-tag">{{ resultTitle }}</span>
      </div>
      <pre>{{ formatJson(resultData) }}</pre>
    </section>
  </main>
</template>

<style scoped>
:global(body) {
  margin: 0;
  font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
  background:
    radial-gradient(circle at top left, #dff6ff 0, transparent 32%),
    linear-gradient(180deg, #fffdf7 0%, #f2f7ff 100%);
  color: #1f2937;
}

:global(*) {
  box-sizing: border-box;
}

.page {
  max-width: 1100px;
  margin: 0 auto;
  padding: 40px 20px 60px;
}

.hero {
  margin-bottom: 20px;
}

.eyebrow {
  margin: 0 0 8px;
  color: #0f766e;
  font-size: 14px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

h1 {
  margin: 0;
  font-size: clamp(30px, 4vw, 48px);
  line-height: 1.05;
}

.subtext {
  max-width: 720px;
  margin-top: 12px;
  color: #475569;
  font-size: 16px;
}

.status-banner {
  margin-bottom: 20px;
  border-radius: 16px;
  padding: 14px 16px;
  font-size: 14px;
  font-weight: 700;
  border: 1px solid transparent;
}

.status-banner.info {
  background: #eef2ff;
  border-color: #c7d2fe;
  color: #4338ca;
}

.status-banner.loading {
  background: #eff6ff;
  border-color: #bfdbfe;
  color: #1d4ed8;
}

.status-banner.success {
  background: #ecfdf5;
  border-color: #a7f3d0;
  color: #047857;
}

.status-banner.error {
  background: #fef2f2;
  border-color: #fecaca;
  color: #b91c1c;
}

.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 20px;
  margin-bottom: 20px;
}

.panel {
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 20px;
  padding: 20px;
  background: rgba(255, 255, 255, 0.9);
  box-shadow: 0 18px 50px rgba(15, 23, 42, 0.08);
  backdrop-filter: blur(8px);
  margin-bottom: 20px;
}

.panel h2 {
  margin-top: 0;
  margin-bottom: 14px;
  font-size: 20px;
}

.result-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.result-tag {
  border-radius: 999px;
  padding: 8px 12px;
  background: #dbeafe;
  color: #1d4ed8;
  font-size: 12px;
  font-weight: 700;
}

input,
textarea {
  width: 100%;
  margin-bottom: 12px;
  border: 1px solid #cbd5e1;
  border-radius: 12px;
  padding: 12px 14px;
  font-size: 14px;
  background: #fff;
}

input:focus,
textarea:focus {
  outline: none;
  border-color: #60a5fa;
  box-shadow: 0 0 0 4px rgba(96, 165, 250, 0.15);
}

textarea {
  resize: vertical;
}

button {
  border: none;
  border-radius: 999px;
  padding: 12px 18px;
  background: linear-gradient(135deg, #0f766e, #2563eb);
  color: #fff;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  transition: transform 0.16s ease, opacity 0.16s ease, box-shadow 0.16s ease;
  box-shadow: 0 10px 24px rgba(37, 99, 235, 0.22);
}

button:hover:not(:disabled) {
  transform: translateY(-1px);
}

button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
  box-shadow: none;
}

.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

.info {
  margin-top: 14px;
  border-top: 1px solid #e2e8f0;
  padding-top: 14px;
}

.info p,
.hint {
  margin: 8px 0 0;
  line-height: 1.5;
}

.hint {
  color: #64748b;
}

pre {
  min-height: 220px;
  overflow: auto;
  margin: 12px 0 0;
  border-radius: 16px;
  padding: 16px;
  background: #0f172a;
  color: #e2e8f0;
  font-size: 13px;
  line-height: 1.5;
}

@media (max-width: 640px) {
  .page {
    padding: 28px 16px 48px;
  }

  .panel {
    padding: 16px;
  }

  .actions {
    flex-direction: column;
  }

  .result-header {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
