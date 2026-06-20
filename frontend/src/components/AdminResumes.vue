<script setup>
import { inject, ref, onMounted } from "vue";
const api = inject("api");
const items = ref([]);
const total = ref(0);
const page = ref(1);
const pageSize = 20;
const search = ref("");

async function load() {
  try {
    const r = await api.adminApi.listAllResumes({ page: page.value, page_size: pageSize, username: search.value });
    items.value = r.items; total.value = r.total;
  } catch {}
}
onMounted(load);

function prev() { if (page.value > 1) { page.value--; load(); } }
function next() { if (page.value * pageSize < total.value) { page.value++; load(); } }
</script>

<template>
  <div>
    <h4>全局简历</h4>
    <div class="inline-form">
      <input v-model="search" placeholder="搜索用户名..." @keyup.enter="page=1;load()" />
      <button class="btn btn-secondary" @click="page=1;load()">搜索</button>
      <span class="page-info">共 {{ total }} 条，第 {{ page }} 页</span>
    </div>
    <div class="table-wrap section-top">
      <table class="task-table">
        <thead><tr><th>ID</th><th>用户</th><th>本地ID</th><th>文件名</th><th>上传时间</th></tr></thead>
        <tbody>
          <tr v-for="r in items" :key="r.id">
            <td>{{ r.id }}</td><td>{{ r.username }}</td><td>{{ r.local_resume_id }}</td>
            <td>{{ r.file_name }}</td><td>{{ (r.created_at || '').slice(0, 16) }}</td>
          </tr>
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
