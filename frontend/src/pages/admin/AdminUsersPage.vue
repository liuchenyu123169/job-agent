<script setup>
import { inject, ref, onMounted } from "vue";

const api = inject("api");
const setMessage = inject("setMessage");
const switchView = inject("switchView");
const users = ref([]);
const expandedId = ref(null);
const userStats = ref({}); // userId → { resumes, jobs, tasks, sessions }

async function loadUsers() {
  try {
    users.value = await api.adminApi.listUsers();
  } catch {}
}
onMounted(loadUsers);

async function toggle(id) {
  if (expandedId.value === id) {
    expandedId.value = null;
    return;
  }
  expandedId.value = id;
  // 加载该用户的资源统计
  if (!userStats.value[id]) {
    try {
      const user = users.value.find((u) => u.id === id);
      const [resumes, jobs, tasks, sessions] = await Promise.all([
        api.adminApi.listAllResumes({ username: user.username, page_size: 1 }),
        api.adminApi.listAllJobs({ username: user.username, page_size: 1 }),
        api.adminApi.listAllTasks({ username: user.username, page_size: 1 }),
        api.adminApi.listAllSessions({ username: user.username, page_size: 1 }),
      ]);
      userStats.value[id] = {
        resumes: resumes.total || 0,
        jobs: jobs.total || 0,
        tasks: tasks.total || 0,
        sessions: sessions.total || 0,
      };
    } catch {
      userStats.value[id] = {};
    }
  }
}

function goUserResumes(username) {
  localStorage.setItem("adminTaskFilters", JSON.stringify({ username }));
  switchView("admin_resumes");
}
function goUserTasks(username) {
  localStorage.setItem("adminTaskFilters", JSON.stringify({ username }));
  switchView("admin_tasks");
}

async function toggleAdmin(user) {
  try {
    await api.adminApi.updateUser(user.id, { is_admin: !user.is_admin });
    setMessage(`${user.username} ${user.is_admin ? "已取消管理员" : "已设为管理员"}`);
    await loadUsers();
  } catch (e) {
    setMessage(e?.response?.data?.detail || "操作失败", true);
  }
}

async function delUser(user) {
  if (!confirm(`确认删除用户 ${user.username} 及其所有数据？此操作不可恢复。`)) return;
  try {
    await api.adminApi.deleteUser(user.id);
    setMessage(`已删除用户 ${user.username}`);
    await loadUsers();
  } catch (e) {
    setMessage(e?.response?.data?.detail || "删除失败", true);
  }
}

defineExpose({ loadUsers });
</script>

<template>
  <div class="admin-users">
    <div style="display: flex; align-items: center; justify-content: space-between">
      <h4>用户管理</h4>
      <button class="btn btn-secondary btn-small" @click="loadUsers">刷新</button>
    </div>
    <div class="table-wrap section-top">
      <table class="task-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>用户名</th>
            <th>管理员</th>
            <th>注册时间</th>
            <th>操作</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <template v-for="u in users" :key="u.id">
            <tr>
              <td>{{ u.id }}</td>
              <td>{{ u.username }}</td>
              <td>{{ u.is_admin ? "是" : "否" }}</td>
              <td>{{ (u.created_at || "").slice(0, 10) }}</td>
              <td>
                <button class="btn btn-secondary btn-small" @click="toggleAdmin(u)">
                  {{ u.is_admin ? "取消管理员" : "设为管理员" }}
                </button>
                <button class="btn btn-ghost btn-small" style="color: #ef4444" @click="delUser(u)">
                  删除
                </button>
              </td>
              <td>
                <button class="btn btn-secondary btn-small" @click="toggle(u.id)">
                  {{ expandedId === u.id ? "收起" : "详情" }}
                </button>
              </td>
            </tr>
            <tr v-if="expandedId === u.id">
              <td colspan="6" style="padding: 16px; background: #f8fafc">
                <div
                  style="
                    display: flex;
                    gap: 16px;
                    flex-wrap: wrap;
                    margin-bottom: 12px;
                    font-size: 12px;
                    color: #64748b;
                  "
                >
                  <span
                    >用户: <strong>{{ u.username }}</strong></span
                  >
                  <span>注册: {{ (u.created_at || "").slice(0, 10) }}</span>
                  <span>管理员: {{ u.is_admin ? "是" : "否" }}</span>
                </div>
                <div v-if="userStats[u.id]" class="stats-grid">
                  <div class="stat-card clickable" @click="goUserResumes(u.username)">
                    <span class="stat-num">{{ userStats[u.id].resumes ?? "..." }}</span
                    ><span class="stat-label">简历</span>
                  </div>
                  <div class="stat-card clickable" @click="goUserResumes(u.username)">
                    <span class="stat-num">{{ userStats[u.id].jobs ?? "..." }}</span
                    ><span class="stat-label">岗位</span>
                  </div>
                  <div class="stat-card clickable" @click="goUserTasks(u.username)">
                    <span class="stat-num">{{ userStats[u.id].tasks ?? "..." }}</span
                    ><span class="stat-label">任务</span>
                  </div>
                  <div class="stat-card clickable">
                    <span class="stat-num">{{ userStats[u.id].sessions ?? "..." }}</span
                    ><span class="stat-label">会话</span>
                  </div>
                </div>
                <div v-else style="color: #94a3b8; font-size: 12px">加载中...</div>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
  margin-top: 8px;
}
.stat-card {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  padding: 12px;
  text-align: center;
}
.stat-card.clickable {
  cursor: pointer;
}
.stat-card.clickable:hover {
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
  border-color: #93c5fd;
}
.stat-num {
  display: block;
  font-size: 20px;
  font-weight: 800;
  color: #2563eb;
}
.stat-label {
  display: block;
  font-size: 11px;
  color: #64748b;
  margin-top: 2px;
}
</style>
