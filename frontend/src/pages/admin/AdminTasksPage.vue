<script setup>
import { inject, ref, onMounted } from "vue";
import TaskTrace from "../../components/TaskTrace.vue";
import { renderMarkdown } from "../../shared/markdown.js";

const api = inject("api");
const items = ref([]);
const total = ref(0);
const page = ref(1);
const pageSize = 20;
const filterType = ref("");
const filterStatus = ref("");
const filterUser = ref("");
const filterSlow = ref(false);
const expandedId = ref(null);

async function load() {
  try {
    const params = { page: page.value, page_size: pageSize };
    if (filterType.value) params.task_type = filterType.value;
    if (filterStatus.value) params.status = filterStatus.value;
    if (filterUser.value) params.username = filterUser.value;
    if (filterSlow.value) params.min_duration_ms = 10000;
    const r = await api.adminApi.listAllTasks(params);
    items.value = r.items; total.value = r.total;
  } catch {}
}

onMounted(() => {
  // 从仪表盘传来的预设筛选
  const saved = localStorage.getItem("adminTaskFilters");
  if (saved) {
    try {
      const f = JSON.parse(saved);
      if (f.task_type) filterType.value = f.task_type;
      if (f.status) filterStatus.value = f.status;
      if (f.hours) { /* 后端暂不支持时间筛选，前端过滤 */ }
      localStorage.removeItem("adminTaskFilters");
    } catch {}
  }
  load();
});

function toggle(id) { expandedId.value = expandedId.value === id ? null : id; }
function prev() { if (page.value > 1) { page.value--; load(); } }
function next() { if (page.value * pageSize < total.value) { page.value++; load(); } }

function totalDuration(traces) {
  if (!traces || !traces.length) return 0;
  return traces.reduce((s, t) => s + (t.duration_ms || 0), 0);
}
</script>

<template>
  <div>
    <h4>全局任务 &amp; 链路追踪</h4>
    <div class="inline-form">
      <input v-model="filterUser" placeholder="用户名..." @keyup.enter="page=1;load()" style="width:100px" />
      <select v-model="filterType" @change="page=1;load()" style="width:140px">
        <option value="">全部类型</option>
        <option>MATCH_ANALYZE</option><option>RESUME_OPTIMIZE</option>
        <option>INTERVIEW_QUESTIONS</option><option>JOB_RECOMMEND</option>
        <option>RESUME_GENERATE</option>
      </select>
      <select v-model="filterStatus" @change="page=1;load()" style="width:100px">
        <option value="">全部状态</option>
        <option>SUCCESS</option><option>FAILED</option>
      </select>
      <label style="font-size:12px;display:flex;align-items:center;gap:4px;white-space:nowrap">
        <input type="checkbox" v-model="filterSlow" @change="page=1;load()" style="width:16px;height:16px" /> 慢任务(&gt;10s)
      </label>
      <button class="btn btn-secondary btn-small" @click="page=1;load()">筛选</button>
      <span class="page-info">共 {{ total }} 条，第 {{ page }} 页</span>
    </div>

    <div class="table-wrap section-top">
      <table class="task-table">
        <thead><tr><th>ID</th><th>类型</th><th>用户</th><th>简历</th><th>岗位</th><th>状态</th><th>耗时</th><th>spans</th><th>时间</th><th></th></tr></thead>
        <tbody>
          <template v-for="t in items" :key="t.id">
            <tr :style="{ background: t.status === 'FAILED' ? '#fef2f2' : '' }">
              <td>{{ t.id }}</td><td>{{ t.task_type }}</td><td>{{ t.username }}</td>
              <td>{{ t.resume_id ?? '-' }}</td><td>{{ t.job_id ?? '-' }}</td>
              <td><span :style="{ color: t.status === 'FAILED' ? '#dc2626' : '#059669', fontWeight: 600 }">{{ t.status }}</span></td>
              <td><strong>{{ totalDuration(t.trace_json || t.trace) }}ms</strong></td>
              <td>{{ (t.trace_json || t.trace || []).length }}</td>
              <td>{{ (t.created_at || '').slice(0, 16) }}</td>
              <td><button class="btn btn-secondary btn-small" @click="toggle(t.id)">{{ expandedId === t.id ? '收起' : '详情' }}</button></td>
            </tr>
            <tr v-if="expandedId === t.id">
              <td colspan="10" style="padding:16px;background:#f8fafc">
                <div style="display:block;margin-bottom:4px;font-size:12px;color:#334155">
                  <div style="margin-bottom:2px"><strong>任务 #{{ t.id }}</strong> — {{ t.task_type }}</div>
                  <div style="margin-bottom:2px">用户: {{ t.username }} | 时间: {{ (t.created_at || '').slice(0, 16) }}</div>
                  <div style="margin-bottom:2px" v-if="t.resume_id || t.job_id">简历 #{{ t.resume_id ?? '-' }} | 岗位 #{{ t.job_id ?? '-' }}</div>
                  <div style="margin-bottom:2px">总耗时: <strong>{{ totalDuration(t.trace_json) }}ms</strong> | spans: {{ (t.trace_json || []).length }}</div>
                </div>
                <TaskTrace v-if="(t.trace_json)?.length" :trace="t.trace_json" />
                <div v-if="!t.trace_json?.length" style="color:#94a3b8;font-size:12px;margin-bottom:8px">无链路追踪数据</div>
                <div v-if="t.output_json" class="section-top">
                  <h5>输出</h5>
                  <template v-if="t.output_json.text && typeof t.output_json.text === 'string'">
                    <div class="output-card"><div class="stream-text stream-done" v-html="renderMarkdown(t.output_json.text)"></div></div>
                  </template>
                  <pre v-else class="code-block" style="max-height:300px">{{ typeof t.output_json === 'string' ? t.output_json : JSON.stringify(t.output_json, null, 2) }}</pre>
                </div>
                <div v-if="t.error_msg" class="section-top">
                  <h5 style="color:#dc2626">错误</h5>
                  <pre class="code-block error-block">{{ t.error_msg }}</pre>
                </div>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>

    <div class="pager" v-if="total > pageSize">
      <button class="btn btn-secondary btn-small" :disabled="page<=1" @click="prev">上一页</button>
      <button class="btn btn-secondary btn-small" :disabled="page*pageSize >= total" @click="next">下一页</button>
    </div>
  </div>
</template>

<style scoped>
.inline-form { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.inline-form input, .inline-form select { height: 32px; border-radius: 8px; border: 1px solid #cbd5e1; padding: 0 8px; font-size: 12px; }
.page-info { font-size: 12px; color: #64748b; margin-left: 8px; }
.pager { display: flex; gap: 8px; margin-top: 12px; justify-content: center; }
</style>
