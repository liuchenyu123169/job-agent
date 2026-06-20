<script setup>
import { inject, ref, onMounted } from "vue";

const api = inject("api");
const setMessage = inject("setMessage");
const users = ref([]);

async function loadUsers() {
  try { users.value = await api.adminApi.listUsers(); } catch {}
}
onMounted(loadUsers);

async function toggleAdmin(user) {
  try {
    await api.adminApi.updateUser(user.id, { is_admin: !user.is_admin });
    setMessage(`${user.username} ${user.is_admin ? "已取消管理员" : "已设为管理员"}`);
    await loadUsers();
  } catch (e) { setMessage(e?.response?.data?.detail || "操作失败", true); }
}

async function delUser(user) {
  if (!confirm(`确认删除用户 ${user.username} 及其所有数据？此操作不可恢复。`)) return;
  try {
    await api.adminApi.deleteUser(user.id);
    setMessage(`已删除用户 ${user.username}`);
    await loadUsers();
  } catch (e) { setMessage(e?.response?.data?.detail || "删除失败", true); }
}

defineExpose({ loadUsers });
</script>

<template>
  <div class="admin-users">
    <h4>用户管理</h4>
    <button class="btn btn-secondary btn-small" @click="loadUsers">刷新</button>
    <div class="table-wrap section-top">
      <table class="task-table">
        <thead><tr><th>ID</th><th>用户名</th><th>管理员</th><th>注册时间</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="u in users" :key="u.id">
            <td>{{ u.id }}</td><td>{{ u.username }}</td>
            <td>{{ u.is_admin ? '是' : '否' }}</td>
            <td>{{ (u.created_at || '').slice(0, 10) }}</td>
            <td>
              <button class="btn btn-secondary btn-small" @click="toggleAdmin(u)">{{ u.is_admin ? '取消管理员' : '设为管理员' }}</button>
              <button class="btn btn-ghost btn-small" style="color:#ef4444" @click="delUser(u)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
