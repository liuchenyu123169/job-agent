<script setup>
import { inject, ref, reactive } from "vue";

const api = inject("api");
const setMessage = inject("setMessage");
const applyResumeSelection = inject("applyResumeSelection");
const fetchResumeList = inject("fetchResumeList");
const loadingMap = inject("loadingMap");

const selectedFile = ref(null);
const detailInput = ref("");
const detailResult = ref(null);
const list = ref([]);

function onFileChange(event) {
  selectedFile.value = (event.target.files || [])[0] || null;
}

async function uploadResume() {
  if (!selectedFile.value) { setMessage("请先选择文件。", true); return; }
  loadingMap.resumeUpload = true;
  try {
    const resp = await api.resumeApi.uploadResume(selectedFile.value);
    applyResumeSelection({ id: resp.resume_id, local_resume_id: resp.local_resume_id, file_name: resp.file_name, content_preview: resp.content_preview });
    await fetchResumeList();
  } catch (err) { setMessage(err?.message || "上传失败", true); }
  finally { loadingMap.resumeUpload = false; }
}

async function fetchDetail() {
  if (!detailInput.value) { setMessage("请输入本地简历编号。", true); return; }
  loadingMap.resumeDetail = true;
  try {
    const resp = await api.resumeApi.getResumeByLocalId(Number(detailInput.value));
    detailResult.value = resp;
    applyResumeSelection(resp);
  } catch (err) { setMessage(err?.message || "查询失败", true); }
  finally { loadingMap.resumeDetail = false; }
}

async function refreshList() {
  loadingMap.resumeList = true;
  try { list.value = (await api.resumeApi.listResumes()).items || []; }
  catch (err) { setMessage(err?.message || "获取列表失败", true); }
  finally { loadingMap.resumeList = false; }
}

defineExpose({ list, refreshList });
</script>

<template>
  <div class="form-stack">
    <label class="field"><span>上传简历文件</span><input type="file" accept=".pdf,.docx,.txt" @change="onFileChange" /></label>
    <button class="btn btn-primary" :disabled="loadingMap.resumeUpload" @click="uploadResume">
      {{ loadingMap.resumeUpload ? "上传中..." : "上传" }}
    </button>
  </div>
  <hr />
  <div class="inline-form">
    <input v-model="detailInput" type="number" min="1" placeholder="本地编号" />
    <button class="btn btn-secondary" :disabled="loadingMap.resumeDetail" @click="fetchDetail">查询</button>
    <button class="btn btn-secondary" @click="refreshList">刷新列表</button>
  </div>
  <div v-if="list.length" class="result-list section-top">
    <div v-for="item in list" :key="item.id" class="result-card">
      <div class="result-card-head">
        <div><h5>#{{ item.local_resume_id }} {{ item.file_name }}</h5></div>
        <button class="btn btn-secondary btn-small" @click="applyResumeSelection(item); $emit('close')">选用</button>
      </div>
      <p>{{ item.content_preview || "暂无预览" }}</p>
    </div>
  </div>
</template>
