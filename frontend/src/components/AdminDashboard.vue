<script setup>
import { inject, ref, onMounted } from "vue";

const api = inject("api");
const stats = ref(null);

onMounted(async () => {
  try { stats.value = await api.adminApi.getStats(); } catch {}
});

function refresh() {
  api.adminApi.getStats().then(s => stats.value = s).catch(() => {});
}
</script>

<template>
  <div class="admin-dashboard">
    <h4>管理仪表盘</h4>
    <button class="btn btn-secondary btn-small" @click="refresh">刷新</button>
    <div v-if="stats" class="stats-grid">
      <div class="stat-card"><span class="stat-num">{{ stats.users }}</span><span class="stat-label">用户</span></div>
      <div class="stat-card"><span class="stat-num">{{ stats.resumes }}</span><span class="stat-label">简历</span></div>
      <div class="stat-card"><span class="stat-num">{{ stats.jobs }}</span><span class="stat-label">岗位</span></div>
      <div class="stat-card"><span class="stat-num">{{ stats.tasks }}</span><span class="stat-label">任务</span></div>
      <div class="stat-card"><span class="stat-num">{{ stats.tasks_24h }}</span><span class="stat-label">24h任务</span></div>
      <div class="stat-card"><span class="stat-num">{{ stats.sessions }}</span><span class="stat-label">会话</span></div>
      <div class="stat-card"><span class="stat-num">{{ stats.messages }}</span><span class="stat-label">消息</span></div>
      <div class="stat-card"><span class="stat-num">{{ stats.avg_task_duration_ms }}ms</span><span class="stat-label">平均耗时</span></div>
    </div>
    <div v-if="stats?.tasks_by_type" class="section-top">
      <h5>任务类型分布</h5>
      <div class="stats-grid">
        <div v-for="(cnt, ttype) in stats.tasks_by_type" :key="ttype" class="stat-card">
          <span class="stat-num small">{{ cnt }}</span><span class="stat-label">{{ ttype }}</span>
        </div>
      </div>
    </div>
    <div v-if="stats?.tasks_by_status" class="section-top">
      <h5>任务状态分布</h5>
      <div class="stats-grid">
        <div v-for="(cnt, status) in stats.tasks_by_status" :key="status" class="stat-card">
          <span class="stat-num small">{{ cnt }}</span><span class="stat-label">{{ status }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.stats-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(100px, 1fr)); gap: 10px; margin-top: 12px; }
.stat-card { background: #f8fafc; border: 1px solid #e5e7eb; border-radius: 10px; padding: 14px; text-align: center; }
.stat-num { display: block; font-size: 24px; font-weight: 800; color: #2563eb; }
.stat-num.small { font-size: 16px; }
.stat-label { display: block; font-size: 11px; color: #64748b; margin-top: 2px; }
</style>
