<script setup>
import { inject, ref, onMounted } from "vue";
import { formatJson, normalizeOutputFields } from "./utils.js";
import TaskTrace from "./TaskTrace.vue";

const api = inject("api");
const items = ref([]);
const total = ref(0);
const page = ref(1);
const pageSize = 20;
const filterType = ref("");
const filterStatus = ref("");
const filterUser = ref("");
const expandedId = ref(null);

async function load() {
  try {
    const params = { page: page.value, page_size: pageSize };
    if (filterType.value) params.task_type = filterType.value;
    if (filterStatus.value) params.status = filterStatus.value;
    if (filterUser.value) params.username = filterUser.value;
    const r = await api.adminApi.listAllTasks(params);
    items.value = r.items;
    total.value = r.total;
  } catch {}
}
onMounted(load);

function toggle(id) { expandedId.value = expandedId.value === id ? null : id; }
function prev() { if (page.value > 1) { page.value--; load(); } }
function next() { if (page.value * pageSize < total.value) { page.value++; load(); } }

function parsed(item) {
  if (!item?.output_json) return null;
  let out = item.output_json;
  if (typeof out === "string") { try { out = JSON.parse(out); } catch { return null; } }
  if (!out || typeof out !== "object") return null;
  return normalizeOutputFields(out);
}
</script>

<template>
  <div>
    <h4>全局任务</h4>
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
      <button class="btn btn-secondary btn-small" @click="page=1;load()">筛选</button>
      <span class="page-info">共 {{ total }} 条，第 {{ page }} 页</span>
    </div>

    <div class="table-wrap section-top">
      <table class="task-table">
        <thead><tr><th>ID</th><th>类型</th><th>用户</th><th>简历ID</th><th>岗位ID</th><th>状态</th><th>时间</th><th></th></tr></thead>
        <tbody>
          <template v-for="t in items" :key="t.id">
            <tr>
              <td>{{ t.id }}</td><td>{{ t.task_type }}</td><td>{{ t.username }}</td>
              <td>{{ t.resume_id ?? '-' }}</td><td>{{ t.job_id ?? '-' }}</td>
              <td>{{ t.status }}</td><td>{{ (t.created_at || '').slice(0, 16) }}</td>
              <td><button class="btn btn-secondary btn-small" @click="toggle(t.id)">{{ expandedId === t.id ? '收起' : '展开' }}</button></td>
            </tr>
            <tr v-if="expandedId === t.id">
              <td colspan="8" style="padding:12px;background:#f8fafc">
                <!-- 追踪时间线 -->
                <TaskTrace :trace="t.trace_json || []" />
                <!-- 结果 -->
                <div v-if="parsed(t)" class="section-top">
                  <h5>结果</h5>
                  <div v-if="parsed(t).analysis?.match_score !== undefined" class="step-detail" style="margin-top:8px">
                    <span class="match-score-big" style="font-size:24px">{{ parsed(t).analysis.match_score }}<span>分</span></span>
                    <div v-if="parsed(t).analysis.advantages?.length"><h6>优势</h6><ul><li v-for="a in parsed(t).analysis.advantages" :key="a">{{ a }}</li></ul></div>
                    <div v-if="parsed(t).analysis.weaknesses?.length"><h6>不足</h6><ul><li v-for="w in parsed(t).analysis.weaknesses" :key="w">{{ w }}</li></ul></div>
                  </div>
                  <div v-if="parsed(t).optimization?.summary" class="step-detail" style="margin-top:8px">
                    <h6>优化建议</h6><p>{{ parsed(t).optimization.summary }}</p>
                  </div>
                  <div v-if="parsed(t).questions" class="step-detail" style="margin-top:8px">
                    <h6>面试题</h6>
                    <div v-for="cat in [['technical_questions','技术题'],['project_questions','项目题'],['behavior_questions','行为题'],['risk_questions','风险题']]" :key="cat[0]">
                      <template v-if="parsed(t).questions[cat[0]]?.length">
                        <strong>{{ cat[1] }}（{{ parsed(t).questions[cat[0]].length }}）</strong>
                        <div v-for="(q, qi) in parsed(t).questions[cat[0]]" :key="qi" class="question-item">
                          <strong>{{ q.question || q }}</strong>
                        </div>
                      </template>
                    </div>
                  </div>
                </div>
                <div v-if="t.error_msg" class="section-top"><h5>错误</h5><pre class="code-block error-block">{{ t.error_msg }}</pre></div>
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
