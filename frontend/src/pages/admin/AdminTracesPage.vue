<script setup>
import { inject, ref, onMounted } from "vue";
import TaskTrace from "../../components/TaskTrace.vue";

const api = inject("api");
const items = ref([]);
const total = ref(0);
const page = ref(1);
const pageSize = 30;
const expandedId = ref(null);

async function load() {
  try {
    const r = await api.adminApi.listTraces({ page: page.value, page_size: pageSize });
    items.value = r.items;
    total.value = r.total;
  } catch {}
}
onMounted(load);

function toggle(id) {
  expandedId.value = expandedId.value === id ? null : id;
}
function prev() {
  if (page.value > 1) {
    page.value--;
    load();
  }
}
function next() {
  if (page.value * pageSize < total.value) {
    page.value++;
    load();
  }
}
function totalDuration(traces) {
  if (!traces || !traces.length) return 0;
  return traces.reduce((s, t) => s + (t.duration_ms || 0), 0);
}
</script>

<template>
  <div>
    <h4>链路追踪（仅显示有 trace 数据的任务）</h4>
    <p style="color: #64748b; font-size: 12px">
      按耗时降序，点击展开查看各阶段时间线和 token 用量。
    </p>
    <div class="table-wrap section-top">
      <table class="task-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>类型</th>
            <th>用户</th>
            <th>简历</th>
            <th>岗位</th>
            <th>总耗时</th>
            <th>spans</th>
            <th>时间</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <template v-for="t in items" :key="t.id">
            <tr>
              <td>{{ t.id }}</td>
              <td>{{ t.task_type }}</td>
              <td>{{ t.username }}</td>
              <td>{{ t.resume_id ?? "-" }}</td>
              <td>{{ t.job_id ?? "-" }}</td>
              <td>
                <strong>{{ totalDuration(t.trace_json) || t.total_duration_ms }}ms</strong>
              </td>
              <td>{{ (t.trace_json || []).length }}</td>
              <td>{{ (t.created_at || "").slice(0, 16) }}</td>
              <td>
                <button class="btn btn-secondary btn-small" @click="toggle(t.id)">
                  {{ expandedId === t.id ? "收起" : "详情" }}
                </button>
              </td>
            </tr>
            <tr v-if="expandedId === t.id">
              <td colspan="9" style="padding: 16px; background: #f8fafc">
                <TaskTrace v-if="t.trace_json?.length" :trace="t.trace_json" />
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>
    <div
      class="pager"
      v-if="total > pageSize"
      style="display: flex; gap: 8px; margin-top: 12px; justify-content: center"
    >
      <button class="btn btn-secondary btn-small" :disabled="page <= 1" @click="prev">
        上一页
      </button>
      <button
        class="btn btn-secondary btn-small"
        :disabled="page * pageSize >= total"
        @click="next"
      >
        下一页
      </button>
    </div>
  </div>
</template>

<style scoped>
.pager {
  display: flex;
  gap: 8px;
  margin-top: 12px;
  justify-content: center;
}
</style>
