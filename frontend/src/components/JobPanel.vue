<script setup>
import { inject, ref } from "vue";

const api = inject("api");
const setMessage = inject("setMessage");
const applyJobSelection = inject("applyJobSelection");
const fetchJobList = inject("fetchJobList");
const loadingMap = inject("loadingMap");

const form = ref({ company: "", title: "", jd_text: "" });
const detailInput = ref("");
const detailResult = ref(null);
const list = ref([]);

async function saveJob() {
  if (!form.value.title || !form.value.jd_text) { setMessage("请填写岗位名称和 JD。", true); return; }
  loadingMap.jobCreate = true;
  try {
    const resp = await api.jobApi.createJob({ company: form.value.company || null, title: form.value.title, jd_text: form.value.jd_text });
    applyJobSelection({ id: resp.job_id, local_job_id: resp.local_job_id, company: form.value.company, title: form.value.title, jd_text: form.value.jd_text });
    await fetchJobList();
  } catch (err) { setMessage(err?.message || "保存失败", true); }
  finally { loadingMap.jobCreate = false; }
}

async function fetchDetail() {
  if (!detailInput.value) { setMessage("请输入本地岗位编号。", true); return; }
  loadingMap.jobDetail = true;
  try {
    const resp = await api.jobApi.getJobByLocalId(Number(detailInput.value));
    detailResult.value = resp;
    applyJobSelection(resp);
  } catch (err) { setMessage(err?.message || "查询失败", true); }
  finally { loadingMap.jobDetail = false; }
}

async function refreshList() {
  loadingMap.jobList = true;
  try { list.value = (await api.jobApi.listJobs()).items || []; }
  catch (err) { setMessage(err?.message || "获取列表失败", true); }
  finally { loadingMap.jobList = false; }
}

defineExpose({ list, refreshList });
</script>

<template>
  <div class="form-stack">
    <label class="field"><span>公司</span><input v-model="form.company" placeholder="如：字节跳动" /></label>
    <label class="field"><span>岗位</span><input v-model="form.title" placeholder="如：后端开发工程师" /></label>
    <label class="field"><span>岗位 JD</span><textarea v-model="form.jd_text" placeholder="粘贴 JD 内容"></textarea></label>
    <button class="btn btn-primary" :disabled="loadingMap.jobCreate" @click="saveJob">
      {{ loadingMap.jobCreate ? "保存中..." : "保存岗位" }}
    </button>
  </div>
  <hr />
  <div class="inline-form">
    <input v-model="detailInput" type="number" min="1" placeholder="本地编号" />
    <button class="btn btn-secondary" :disabled="loadingMap.jobDetail" @click="fetchDetail">查询</button>
    <button class="btn btn-secondary" @click="refreshList">刷新列表</button>
  </div>
  <div v-if="list.length" class="result-list section-top">
    <div v-for="item in list" :key="item.id" class="result-card">
      <div class="result-card-head">
        <div><h5>#{{ item.local_job_id }} {{ item.company || "?" }} / {{ item.title }}</h5></div>
        <button class="btn btn-secondary btn-small" @click="applyJobSelection(item); $emit('close')">选用</button>
      </div>
      <p>{{ item.jd_preview || "暂无内容" }}</p>
    </div>
  </div>
</template>
