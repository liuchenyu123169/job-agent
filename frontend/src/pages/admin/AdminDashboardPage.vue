<script setup>
import { inject, ref, onMounted } from "vue";

const api = inject("api");
const switchView = inject("switchView");
const stats = ref(null);

onMounted(refresh);
function refresh() {
  api.adminApi
    .getStats()
    .then((s) => (stats.value = s))
    .catch(() => {});
}

function go(key) {
  switchView(key);
}
function goTasks(filters) {
  // 通过 localStorage 传筛选参数给 AdminTasks
  if (filters) localStorage.setItem("adminTaskFilters", JSON.stringify(filters));
  switchView("admin_tasks");
}
</script>

<template>
  <div class="admin-dashboard">
    <div style="display: flex; align-items: center; justify-content: space-between">
      <h4>管理仪表盘</h4>
      <button class="btn btn-secondary btn-small" @click="refresh">刷新</button>
    </div>

    <!-- 核心指标（可点击跳转） -->
    <div v-if="stats" class="stats-grid">
      <div class="stat-card clickable" @click="go('admin_users')">
        <span class="stat-num">{{ stats.users }}</span
        ><span class="stat-label">👥 用户</span>
      </div>
      <div class="stat-card clickable" @click="go('admin_resumes')">
        <span class="stat-num">{{ stats.resumes }}</span
        ><span class="stat-label">📄 简历</span>
      </div>
      <div class="stat-card clickable" @click="go('admin_jobs')">
        <span class="stat-num">{{ stats.jobs }}</span
        ><span class="stat-label">💼 岗位</span>
      </div>
      <div class="stat-card clickable" @click="go('admin_tasks')">
        <span class="stat-num">{{ stats.tasks }}</span
        ><span class="stat-label">📋 任务</span>
      </div>
      <div class="stat-card clickable" @click="goTasks({ hours: 24 })">
        <span class="stat-num">{{ stats.tasks_24h }}</span
        ><span class="stat-label">🕐 24h任务</span>
      </div>
      <div class="stat-card clickable" @click="go('admin_sessions')">
        <span class="stat-num">{{ stats.sessions }}</span
        ><span class="stat-label">💬 会话</span>
      </div>
      <div class="stat-card clickable" @click="go('admin_sessions')">
        <span class="stat-num">{{ stats.messages }}</span
        ><span class="stat-label">✉️ 消息</span>
      </div>
      <div class="stat-card">
        <span class="stat-num">{{ stats.avg_task_duration_ms }}ms</span
        ><span class="stat-label">⏱ 平均耗时</span>
      </div>
    </div>

    <!-- 风险视图 -->
    <div v-if="stats" class="section-top">
      <div v-if="stats.tasks_by_status" class="section-top">
        <h5>任务状态分布</h5>
        <div class="stats-grid small">
          <div
            v-for="(cnt, status) in stats.tasks_by_status"
            :key="status"
            class="stat-card clickable"
            :style="{ borderColor: status === 'FAILED' ? '#fecaca' : '#e5e7eb' }"
            @click="goTasks({ status: status })"
          >
            <span
              class="stat-num small"
              :style="{
                color:
                  status === 'FAILED' ? '#dc2626' : status === 'SUCCESS' ? '#059669' : '#2563eb',
              }"
              >{{ cnt }}</span
            >
            <span class="stat-label">{{
              status === "FAILED" ? "❌ 失败" : status === "SUCCESS" ? "✅ 成功" : status
            }}</span>
          </div>
        </div>
      </div>
      <div v-if="stats.tasks_by_type" class="section-top">
        <h5>任务类型分布</h5>
        <div class="stats-grid small">
          <div
            v-for="(cnt, ttype) in stats.tasks_by_type"
            :key="ttype"
            class="stat-card clickable"
            @click="goTasks({ task_type: ttype })"
          >
            <span class="stat-num small">{{ cnt }}</span
            ><span class="stat-label">{{ ttype }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-top: 12px;
}
.stats-grid.small {
  grid-template-columns: repeat(4, 1fr);
}
.stat-card {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 18px 14px;
  text-align: center;
  transition: box-shadow 0.15s;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
}
.stat-card.clickable {
  cursor: pointer;
}
.stat-card.clickable:hover {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  border-color: #93c5fd;
}
.stat-num {
  display: block;
  font-size: 28px;
  font-weight: 800;
  color: #2563eb;
}
.stat-num.small {
  font-size: 18px;
}
.stat-label {
  display: block;
  font-size: 12px;
  color: #64748b;
  margin-top: 4px;
}
</style>
