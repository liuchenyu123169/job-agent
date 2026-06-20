<script setup>
import { inject, ref, onMounted } from "vue";
const api = inject("api");
const items = ref([]);
const total = ref(0);
const page = ref(1);
const pageSize = 20;
const search = ref("");
const expandedId = ref(null);
const sessionMsgs = ref({});

async function load() {
  try {
    const r = await api.adminApi.listAllSessions({ page: page.value, page_size: pageSize, username: search.value });
    items.value = r.items; total.value = r.total;
  } catch {}
}
onMounted(load);

async function toggle(sessionId) {
  if (expandedId.value === sessionId) { expandedId.value = null; return; }
  expandedId.value = sessionId;
  if (!sessionMsgs.value[sessionId]) {
    try {
      sessionMsgs.value[sessionId] = await api.copilotApi.getSessionMessages(sessionId);
    } catch { sessionMsgs.value[sessionId] = []; }
  }
}

function prev() { if (page.value > 1) { page.value--; load(); } }
function next() { if (page.value * pageSize < total.value) { page.value++; load(); } }
</script>

<template>
  <div>
    <h4>全局会话</h4>
    <div class="inline-form">
      <input v-model="search" placeholder="搜索用户名..." @keyup.enter="page=1;load()" />
      <button class="btn btn-secondary" @click="page=1;load()">搜索</button>
      <span class="page-info">共 {{ total }} 条，第 {{ page }} 页</span>
    </div>
    <div class="table-wrap section-top">
      <table class="task-table">
        <thead><tr><th>ID</th><th>用户</th><th>目标</th><th>状态</th><th>创建时间</th><th></th></tr></thead>
        <tbody>
          <template v-for="s in items" :key="s.id">
            <tr>
              <td>{{ s.id }}</td><td>{{ s.username }}</td>
              <td>{{ (s.goal || '').slice(0, 30) }}{{ (s.goal || '').length > 30 ? '...' : '' }}</td>
              <td>{{ s.status }}</td><td>{{ (s.created_at || '').slice(0, 16) }}</td>
              <td><button class="btn btn-secondary btn-small" @click="toggle(s.id)">{{ expandedId === s.id ? '收起' : '消息' }}</button></td>
            </tr>
            <tr v-if="expandedId === s.id">
              <td colspan="6" style="padding:12px;background:#f8fafc">
                <div v-if="sessionMsgs[s.id]?.length">
                  <div v-for="(m, i) in sessionMsgs[s.id]" :key="i" :style="{ marginBottom: '6px', fontSize: '13px' }">
                    <strong :style="{ color: m.role === 'user' ? '#2563eb' : '#059669' }">{{ m.role === 'user' ? '用户' : 'Copilot' }}:</strong>
                    <span style="color:#334155">{{ (m.content || '').replace('__COPILOT_REPORT__', '').slice(0, 200) }}{{ (m.content || '').length > 200 ? '...' : '' }}</span>
                  </div>
                </div>
                <div v-else style="color:#94a3b8;font-size:12px">暂无消息</div>
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
.inline-form { display: flex; gap: 8px; align-items: center; }
.inline-form input { width: 180px; }
.page-info { font-size: 12px; color: #64748b; margin-left: 8px; }
.pager { display: flex; gap: 8px; margin-top: 12px; justify-content: center; }
</style>
