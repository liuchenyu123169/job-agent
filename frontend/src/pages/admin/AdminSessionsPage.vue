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
    const r = await api.adminApi.listAllSessions({
      page: page.value,
      page_size: pageSize,
      username: search.value,
    });
    items.value = r.items;
    total.value = r.total;
  } catch {}
}
onMounted(load);

async function toggle(sessionId) {
  if (expandedId.value === sessionId) {
    expandedId.value = null;
    return;
  }
  expandedId.value = sessionId;
  if (!sessionMsgs.value[sessionId]) {
    try {
      sessionMsgs.value[sessionId] = await api.copilotApi.getSessionMessages(sessionId);
    } catch {
      sessionMsgs.value[sessionId] = [];
    }
  }
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

function parseTaskIds(session) {
  if (!session) return [];
  try {
    if (session.task_ids_json) {
      const parsed =
        typeof session.task_ids_json === "string"
          ? JSON.parse(session.task_ids_json)
          : session.task_ids_json;
      return Array.isArray(parsed) ? parsed : [];
    }
  } catch {
    return [];
  }
  return [];
}
</script>

<template>
  <div>
    <h4>全局会话</h4>
    <div class="inline-form">
      <input
        v-model="search"
        placeholder="搜索用户名..."
        @keyup.enter="
          page = 1;
          load();
        "
      />
      <button
        class="btn btn-secondary btn-small"
        @click="
          page = 1;
          load();
        "
      >
        搜索
      </button>
      <span class="page-info">共 {{ total }} 条，第 {{ page }} 页</span>
    </div>
    <div class="table-wrap section-top">
      <table class="task-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>用户</th>
            <th>目标</th>
            <th>状态</th>
            <th>任务</th>
            <th>创建时间</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <template v-for="s in items" :key="s.id">
            <tr :style="{ background: s.status === 'ERROR' ? '#fef2f2' : '' }">
              <td>{{ s.id }}</td>
              <td>{{ s.username }}</td>
              <td>
                {{ (s.goal || "").slice(0, 30) }}{{ (s.goal || "").length > 30 ? "..." : "" }}
              </td>
              <td>
                <span
                  :style="{
                    color:
                      s.status === 'ERROR'
                        ? '#dc2626'
                        : s.status === 'COMPLETED'
                          ? '#059669'
                          : '#64748b',
                    fontWeight: 600,
                  }"
                  >{{ s.status }}</span
                >
              </td>
              <td style="font-size: 11px">{{ parseTaskIds(s).join(", ") || "-" }}</td>
              <td>{{ (s.created_at || "").slice(0, 16) }}</td>
              <td>
                <button class="btn btn-secondary btn-small" @click="toggle(s.id)">
                  {{ expandedId === s.id ? "收起" : "消息" }}
                </button>
              </td>
            </tr>
            <tr v-if="expandedId === s.id">
              <td colspan="7" style="padding: 16px; background: #f8fafc">
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
                    >目标: <strong>{{ s.goal }}</strong></span
                  >
                  <span v-if="parseTaskIds(s).length"
                    >关联任务: {{ parseTaskIds(s).join(", ") }}</span
                  >
                  <span v-if="s.messages_summary">摘要: {{ s.messages_summary }}</span>
                </div>
                <h5>消息记录</h5>
                <div v-if="sessionMsgs[s.id]?.length">
                  <div
                    v-for="(m, i) in sessionMsgs[s.id]"
                    :key="i"
                    style="
                      margin-bottom: 8px;
                      font-size: 13px;
                      background: #fff;
                      border: 1px solid #e5e7eb;
                      border-radius: 8px;
                      padding: 8px 12px;
                    "
                  >
                    <strong :style="{ color: m.role === 'user' ? '#2563eb' : '#059669' }">{{
                      m.role === "user" ? "👤 用户" : "🤖 Copilot"
                    }}</strong>
                    <div style="color: #334155; margin-top: 4px; white-space: pre-wrap">
                      {{ (m.content || "").replace("__COPILOT_REPORT__", "").slice(0, 500)
                      }}{{ (m.content || "").length > 500 ? "..." : "" }}
                    </div>
                  </div>
                </div>
                <div v-else style="color: #94a3b8; font-size: 12px">暂无消息</div>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>
    <div class="pager" v-if="total > pageSize">
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
.inline-form {
  display: flex;
  gap: 8px;
  align-items: center;
}
.inline-form input {
  width: 180px;
  height: 32px;
  border-radius: 8px;
  border: 1px solid #cbd5e1;
  padding: 0 8px;
  font-size: 12px;
}
.page-info {
  font-size: 12px;
  color: #64748b;
  margin-left: 8px;
}
.pager {
  display: flex;
  gap: 8px;
  margin-top: 12px;
  justify-content: center;
}
</style>
