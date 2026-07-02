<script setup>
import { inject, ref } from "vue";

const api = inject("api");
const token = inject("token");
const setMessage = inject("setMessage");

const evalWorkflows = ref([
  "match_analyze",
  "interview_questions",
  "resume_optimize",
  "resume_generate",
]);
const evalWorkflow = ref("match_analyze");
const evalUseJudge = ref(true);
const evalRunning = ref(false);
const evalResult = ref(null);

async function runEvaluation() {
  evalRunning.value = true;
  evalResult.value = null;
  try {
    if (!token.value) {
      throw new Error("未登录，无法执行测评");
    }
    const data = await api.evaluationApi.runEvaluation({
      workflows: [evalWorkflow.value],
      llm_judge: evalUseJudge.value,
      judge_samples: 3,
    });
    evalResult.value = data;
  } catch (err) {
    const errorMessage = String(err?.response?.data?.detail || err?.message || err);
    evalResult.value = { error: errorMessage };
    setMessage?.(errorMessage, true);
  } finally {
    evalRunning.value = false;
  }
}
</script>

<template>
  <div
    class="eval-panel-inline section-top"
    style="padding: 24px; max-width: 600px; margin: 0 auto"
  >
    <h4>自动化测评</h4>
    <p>选择 workflow 并运行测评，结果会保存到 `evaluation_results/` 目录。</p>
    <div class="form-stack">
      <div class="field">
        <span>Workflow</span>
        <select
          v-model="evalWorkflow"
          style="
            width: 100%;
            height: 40px;
            border-radius: 10px;
            padding: 0 12px;
            border: 1px solid #cbd5e1;
          "
        >
          <option v-for="workflow in evalWorkflows" :key="workflow" :value="workflow">
            {{ workflow }}
          </option>
        </select>
      </div>
      <div class="field">
        <span>LLM Judge</span>
        <input v-model="evalUseJudge" type="checkbox" />
        启用 LLM 质量评分，耗时会更长。
      </div>
      <button class="btn btn-primary" :disabled="evalRunning" @click="runEvaluation">
        {{ evalRunning ? "测评中..." : "运行测评" }}
      </button>
    </div>
    <div
      v-if="evalResult"
      style="
        margin-top: 16px;
        background: #f8fafc;
        border-radius: 12px;
        padding: 16px;
        max-height: 400px;
        overflow: auto;
      "
    >
      <pre style="font-size: 12px; white-space: pre-wrap; margin: 0">{{
        JSON.stringify(evalResult, null, 2)
      }}</pre>
    </div>
  </div>
</template>
