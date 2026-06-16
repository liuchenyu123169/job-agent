<script setup>
import { inject, ref } from "vue";
import { formatJson } from "./utils.js";

const api = inject("api");
const setMessage = inject("setMessage");
const loadingMap = inject("loadingMap");

const filterTaskType = ref("");
const items = ref([]);
const selectedTask = ref(null);

async function fetchTasks() {
  loadingMap.tasks = true;
  try {
    const params = {};
    if (filterTaskType.value.trim()) params.task_type = filterTaskType.value.trim();
    items.value = (await api.taskApi.listTasks(params)).items || [];
  } catch (err) { setMessage(err?.message || "获取任务失败", true); }
  finally { loadingMap.tasks = false; }
}

async function fetchDetail(taskId) {
  loadingMap.taskDetail = true;
  selectedTask.value = null;
  try {
    const task = await api.taskApi.getTask(taskId);
    selectedTask.value = task;
    setMessage(`已加载任务 #${taskId}`);
  } catch (err) { setMessage(err?.message || "获取详情失败", true); }
  finally { loadingMap.taskDetail = false; }
}

defineExpose({ items, fetchTasks });
</script>

<template>
  <div class="inline-form">
    <input v-model="filterTaskType" placeholder="如 MATCH_ANALYZE" />
    <button class="btn btn-secondary" @click="fetchTasks">刷新</button>
  </div>
  <div class="table-wrap section-top">
    <table class="task-table">
      <thead><tr><th>ID</th><th>类型</th><th>状态</th><th>时间</th><th></th></tr></thead>
      <tbody>
        <tr v-for="t in items" :key="t.id">
          <td>{{ t.id }}</td><td>{{ t.task_type }}</td><td>{{ t.status }}</td><td>{{ t.created_at }}</td>
          <td><button class="btn btn-secondary btn-small" @click="fetchDetail(t.id)">详情</button></td>
        </tr>
      </tbody>
    </table>
  </div>
  <div v-if="selectedTask" class="task-detail section-top">
    <div class="task-detail-head">
      <h5>任务 #{{ selectedTask.id }} 详情</h5>
      <button class="btn btn-ghost btn-small" @click="selectedTask = null">✕ 关闭</button>
    </div>
    <div class="info-list">
      <div class="info-item"><span>类型</span><strong>{{ selectedTask.task_type }}</strong></div>
      <div class="info-item"><span>状态</span><strong>{{ selectedTask.status }}</strong></div>
      <div class="info-item"><span>简历ID</span><strong>{{ selectedTask.resume_id ?? '-' }}</strong></div>
      <div class="info-item"><span>岗位ID</span><strong>{{ selectedTask.job_id ?? '-' }}</strong></div>
    </div>
    <div v-if="selectedTask.output_json" class="section-top">
      <h5>结果</h5>
      <pre class="code-block">{{ formatJson(selectedTask.output_json) }}</pre>
    </div>
    <div v-if="selectedTask.error_msg" class="section-top">
      <h5>错误信息</h5>
      <pre class="code-block error-block">{{ selectedTask.error_msg }}</pre>
    </div>
  </div>
</template>
