<script setup>
import { inject, ref, onMounted } from "vue";
const api = inject("api");
const items = ref([]);
const total = ref(0);
const page = ref(1);
const pageSize = 20;
const search = ref("");
const expandedId = ref(null);

async function load() {
  try {
    const r = await api.adminApi.listAllJobs({
      page: page.value,
      page_size: pageSize,
      username: search.value,
    });
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
</script>

<template>
  <div>
    <h4>全局岗位</h4>
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
            <th>本地ID</th>
            <th>公司</th>
            <th>职位</th>
            <th>创建时间</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <template v-for="j in items" :key="j.id">
            <tr>
              <td>{{ j.id }}</td>
              <td>{{ j.username }}</td>
              <td>{{ j.local_job_id }}</td>
              <td>{{ j.company }}</td>
              <td>{{ j.title }}</td>
              <td>{{ (j.created_at || "").slice(0, 16) }}</td>
              <td>
                <button class="btn btn-secondary btn-small" @click="toggle(j.id)">
                  {{ expandedId === j.id ? "收起" : "详情" }}
                </button>
              </td>
            </tr>
            <tr v-if="expandedId === j.id">
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
                    >用户: <strong>{{ j.username }}</strong></span
                  >
                  <span>{{ j.company }} — {{ j.title }}</span>
                  <span>创建: {{ (j.created_at || "").slice(0, 16) }}</span>
                </div>
                <h5>岗位 JD</h5>
                <pre class="code-block" style="max-height: 400px; white-space: pre-wrap">{{
                  j.jd_text || "(无 JD 内容)"
                }}</pre>
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
