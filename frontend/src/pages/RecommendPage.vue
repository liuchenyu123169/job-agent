<script setup>
import { inject, ref } from "vue";
import { getMatchScore } from "../shared/format.js";

const api = inject("api");
const setMessage = inject("setMessage");
const applyJobSelection = inject("applyJobSelection");
const currentResume = inject("currentResume");
const fetchTasks = inject("fetchTasks");
const loadingMap = inject("loadingMap");

const topK = ref(5);
const maxJobs = ref(10);
const result = ref(null);

async function run() {
  if (!currentResume.id) {
    setMessage("请先选择当前简历。", true);
    return;
  }
  loadingMap.recommend = true;
  try {
    result.value = await api.agentApi.recommendJobs({
      resume_id: Number(currentResume.id),
      top_k: Number(topK.value) || 5,
      max_jobs: Number(maxJobs.value) || 10,
    });
    await fetchTasks();
  } catch (err) {
    setMessage(err?.message || "推荐失败", true);
  } finally {
    loadingMap.recommend = false;
  }
}
</script>

<template>
  <div class="grid form-grid">
    <label class="field"
      ><span>Top K</span><input v-model="topK" type="number" min="1" max="10"
    /></label>
    <label class="field"
      ><span>Max Jobs</span><input v-model="maxJobs" type="number" min="1" max="20"
    /></label>
  </div>
  <button class="btn btn-primary" :disabled="loadingMap.recommend" @click="run">
    {{ loadingMap.recommend ? "推荐中..." : "开始推荐" }}
  </button>
  <div v-if="result?.items?.length" class="result-list section-top">
    <div v-for="item in result.items" :key="item.job_id" class="result-card">
      <div class="result-card-head">
        <div>
          <h5>{{ item.company || "?" }} / {{ item.title }}</h5>
          <p>匹配 {{ getMatchScore(item) }} 分</p>
        </div>
        <button
          class="btn btn-secondary btn-small"
          @click="
            applyJobSelection({
              id: item.job_id,
              local_job_id: item.local_job_id,
              company: item.company,
              title: item.title,
            });
            $emit('close');
          "
        >
          选用
        </button>
      </div>
      <p>{{ item.match_reason || "" }}</p>
    </div>
  </div>
</template>
