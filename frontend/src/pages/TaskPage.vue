<script setup>
import { inject, ref, computed } from "vue";
import { formatJson, normalizeOutputFields } from "../shared/format.js";
import TaskTrace from "../components/TaskTrace.vue";

const api = inject("api");
const setMessage = inject("setMessage");
const loadingMap = inject("loadingMap");

const filterTaskType = ref("");
const items = ref([]);
const selectedTask = ref(null);

async function fetchTasks() {
  loadingMap.tasks = true;
  try {
    const params = {};
    if (filterTaskType.value.trim()) params.task_type = filterTaskType.value.trim();
    items.value = (await api.taskApi.listTasks(params)).items || [];
  } catch (err) { setMessage(err?.message || "获取任务失败", true); }
  finally { loadingMap.tasks = false; }
}

async function fetchDetail(taskId) {
  loadingMap.taskDetail = true;
  selectedTask.value = null;
  try {
    const task = await api.taskApi.getTask(taskId);
    selectedTask.value = task;
    setMessage(`已加载任务 #${taskId}`);
  } catch (err) { setMessage(err?.message || "获取详情失败", true); }
  finally { loadingMap.taskDetail = false; }
}

// 解析并规范化 output_json 供模板语义渲染
const parsedOutput = computed(() => {
  const task = selectedTask.value;
  if (!task?.output_json) return null;
  let out = task.output_json;
  if (typeof out === "string") {
    try { out = JSON.parse(out); } catch { return null; }
  }
  if (!out || typeof out !== "object") return null;
  const normalized = normalizeOutputFields(out);
  // 检测是否包含已知的语义数据类型
  normalized._hasKnownContent = ["analysis", "optimization", "questions", "generated_resume", "items"].some(k => {
    const v = normalized[k];
    if (Array.isArray(v)) return v.length > 0;
    if (typeof v === "object" && v !== null) return Object.keys(v).length > 0;
    return Boolean(v);
  });
  return normalized;
});

defineExpose({ items, fetchTasks });
</script>

<template>
  <div class="inline-form">
    <input v-model="filterTaskType" placeholder="如 MATCH_ANALYZE" />
    <button class="btn btn-secondary" @click="fetchTasks">刷新</button>
  </div>
  <div class="table-wrap section-top">
    <table class="task-table">
      <thead><tr><th>ID</th><th>类型</th><th>状态</th><th>时间</th><th></th></tr></thead>
      <tbody>
        <tr v-for="t in items" :key="t.id">
          <td>{{ t.id }}</td><td>{{ t.task_type }}</td><td>{{ t.status }}</td><td>{{ t.created_at }}</td>
          <td><button class="btn btn-secondary btn-small" @click="fetchDetail(t.id)">详情</button></td>
        </tr>
      </tbody>
    </table>
  </div>
  <div v-if="selectedTask" class="task-detail section-top">
    <div class="task-detail-head">
      <h5>任务 #{{ selectedTask.id }} 详情</h5>
      <button class="btn btn-ghost btn-small" @click="selectedTask = null">✕ 关闭</button>
    </div>
    <div class="info-list">
      <div class="info-item"><span>类型</span><strong>{{ selectedTask.task_type }}</strong></div>
      <div class="info-item"><span>状态</span><strong>{{ selectedTask.status }}</strong></div>
      <div class="info-item"><span>简历ID</span><strong>{{ selectedTask.resume_id ?? '-' }}</strong></div>
      <div class="info-item"><span>岗位ID</span><strong>{{ selectedTask.job_id ?? '-' }}</strong></div>
    </div>
    <!-- 结构化结果渲染 -->
    <div v-if="parsedOutput" class="result-sections section-top">
      <h5>结果</h5>

      <!-- 匹配分析 -->
      <template v-if="parsedOutput.analysis?.match_score !== undefined">
        <div class="step-detail">
          <div class="match-score-big">{{ parsedOutput.analysis.match_score }}<span>分</span></div>
          <p v-if="parsedOutput.analysis.match_reason" class="detail-text">{{ parsedOutput.analysis.match_reason }}</p>
          <div v-if="parsedOutput.analysis.advantages?.length" class="detail-item">
            <h6>优势</h6><ul><li v-for="a in parsedOutput.analysis.advantages" :key="a">{{ a }}</li></ul>
          </div>
          <div v-if="parsedOutput.analysis.weaknesses?.length" class="detail-item">
            <h6>不足</h6><ul><li v-for="w in parsedOutput.analysis.weaknesses" :key="w">{{ w }}</li></ul>
          </div>
          <div v-if="parsedOutput.analysis.suggestions?.length" class="detail-item">
            <h6>建议</h6><ul><li v-for="s in parsedOutput.analysis.suggestions" :key="s">{{ s }}</li></ul>
          </div>
        </div>
      </template>

      <!-- 简历优化 -->
      <template v-if="parsedOutput.optimization">
        <div class="step-detail">
          <p v-if="parsedOutput.optimization.summary" class="detail-text">{{ parsedOutput.optimization.summary }}</p>
          <div v-if="parsedOutput.optimization.skill_keywords?.length" class="detail-item">
            <h6>技能关键词</h6>
            <div class="tag-list"><span v-for="k in parsedOutput.optimization.skill_keywords" :key="k" class="tag">{{ k }}</span></div>
          </div>
          <div v-if="parsedOutput.optimization.project_suggestions?.length" class="detail-item">
            <h6>项目建议</h6><ul><li v-for="p in parsedOutput.optimization.project_suggestions" :key="p">{{ p }}</li></ul>
          </div>
          <div v-if="parsedOutput.optimization.resume_rewrite_suggestions?.length" class="detail-item">
            <h6>简历改写建议</h6><ul><li v-for="r in parsedOutput.optimization.resume_rewrite_suggestions" :key="r">{{ r }}</li></ul>
          </div>
          <div v-if="parsedOutput.optimization.risk_points?.length" class="detail-item">
            <h6>风险点</h6><ul><li v-for="r in parsedOutput.optimization.risk_points" :key="r">{{ r }}</li></ul>
          </div>
        </div>
      </template>

      <!-- 面试题 -->
      <template v-if="parsedOutput.questions">
        <div class="step-detail">
          <div v-for="cat in [['technical_questions','技术题'],['project_questions','项目题'],['behavior_questions','行为题'],['risk_questions','风险题']]" :key="cat[0]">
            <template v-if="parsedOutput.questions[cat[0]]?.length">
              <h6>{{ cat[1] }}（{{ parsedOutput.questions[cat[0]].length }}）</h6>
              <div v-for="(q, qi) in parsedOutput.questions[cat[0]]" :key="qi" class="question-item">
                <strong>{{ q.question || q }}</strong>
                <p v-if="q.why_ask" class="detail-text">考察点：{{ q.why_ask }}</p>
                <p v-if="q.answer_hint" class="detail-text">提示：{{ q.answer_hint }}</p>
              </div>
            </template>
          </div>
        </div>
      </template>

      <!-- 简历生成 -->
      <div v-if="parsedOutput.generated_resume" class="step-detail">
        <h6>生成的简历</h6>
        <div class="generated-resume-text" v-html="parsedOutput.generated_resume.replace(/\n/g, '<br>')"></div>
      </div>

      <!-- 岗位推荐 -->
      <div v-if="parsedOutput.items?.length" class="step-detail">
        <h6>推荐岗位（{{ parsedOutput.items.length }}）</h6>
        <div v-for="(item, ii) in parsedOutput.items" :key="ii" class="detail-item">
          <strong>{{ item.title || item.name || `#${ii+1}` }}</strong>
          <span v-if="item.match_score"> — {{ item.match_score }} 分</span>
        </div>
      </div>

      <!-- 兜底：无法识别类型 → raw JSON -->
      <pre v-if="!parsedOutput._hasKnownContent"
        class="code-block">{{ formatJson(selectedTask.output_json) }}</pre>
    </div>

    <div v-if="selectedTask.error_msg" class="section-top">
      <h5>错误信息</h5>
      <pre class="code-block error-block">{{ selectedTask.error_msg }}</pre>
    </div>

    <!-- 执行链路追踪 -->
    <TaskTrace :trace="selectedTask.trace_json || []" />
  </div>
</template>
