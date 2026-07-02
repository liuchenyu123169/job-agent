<script setup>
import { renderMarkdown } from "../shared/markdown.js";

defineProps({
  role: { type: String, default: "copilot" },
  text: { type: String, default: "" },
  steps: { type: Array, default: null },
  streamTextMap: { type: Object, default: () => ({}) },
  final: { type: Object, default: null },
  error: { type: String, default: null },
  status: { type: String, default: null },
});

const SEARCH_TOOLS = ["public_search", "search_knowledge"];

function isSearchItems(step) {
  return (
    SEARCH_TOOLS.includes(step?.tool) &&
    Array.isArray(step?.summary?.items) &&
    step.summary.items.length > 0
  );
}

function getSearchItems(step) {
  return step.summary.items;
}

function renderStepContent(streamText, stepStatus) {
  const html = renderMarkdown(streamText || "");
  if (stepStatus === "running") return html + '<span class="cursor-blink">▋</span>';
  return html;
}
</script>

<template>
  <div class="msg-wrapper" :class="role">
    <!-- 用户消息 -->
    <div v-if="role === 'user'" class="msg-bubble user-bubble">{{ text }}</div>

    <!-- Copilot 纯文本消息（无 steps） -->
    <div v-else-if="text && !steps" class="msg-bubble copilot-bubble">
      <div class="msg-text" v-html="text.replace(/\n/g, '<br>')"></div>
    </div>

    <!-- Copilot 带 steps 的消息卡片 -->
    <div v-else-if="steps" class="msg-card">
      <div v-for="step in steps" :key="step.tool" class="step-block" :class="'step-' + step.status">
        <div class="step-row">
          <span class="step-icon">{{
            step.status === "running" ? "⏳" : step.status === "done" ? "✓" : "✗"
          }}</span>
          <span class="step-label">{{ step.label || step.tool }}</span>
        </div>

        <!-- 运行中：流式文本 + 光标 -->
        <div
          v-if="step.status === 'running' && streamTextMap[step.tool]"
          class="stream-text"
          v-html="renderStepContent(streamTextMap[step.tool], step.status)"
        ></div>

        <!-- 完成态 + 搜索工具 + 有 items：结构化列表替换流式文本 -->
        <div v-else-if="isSearchItems(step)" class="search-result-list">
          <div
            v-for="(item, i) in getSearchItems(step)"
            :key="item.url || i"
            class="search-result-item"
          >
            <a class="search-result-title" :href="item.url" target="_blank" rel="noreferrer">
              {{ i + 1 }}. {{ item.title || item.url }}
            </a>
            <div v-if="item.snippet" class="search-result-snippet">{{ item.snippet }}</div>
            <div v-if="item.source" class="search-result-source">{{ item.source }}</div>
          </div>
        </div>

        <!-- 完成态 + 非搜索：Markdown 文本（无光标） -->
        <div
          v-else-if="streamTextMap[step.tool]"
          class="stream-text"
          :class="{ 'stream-done': step.status === 'done' }"
          v-html="renderStepContent(streamTextMap[step.tool], step.status)"
        ></div>
      </div>

      <div v-if="final" class="msg-final">
        <p v-if="status === 'PARTIAL'" class="partial-warning">部分步骤执行失败</p>
        <p v-if="status === 'ERROR'" class="partial-error">所有步骤执行失败</p>
        <div
          v-if="final?.summary"
          class="msg-final-summary"
          v-html="renderMarkdown(final.summary)"
        ></div>
      </div>
      <div v-if="error" class="msg-error">{{ error }}</div>
    </div>
  </div>
</template>

<style scoped>
.search-result-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 8px;
}

.search-result-item {
  padding: 12px 14px;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  background: #fafafa;
}

.search-result-title {
  display: inline-block;
  font-weight: 600;
  color: #2563eb;
  text-decoration: none;
  margin-bottom: 6px;
}

.search-result-title:hover {
  text-decoration: underline;
}

.search-result-snippet {
  color: #374151;
  line-height: 1.6;
}

.search-result-source {
  display: inline-block;
  margin-top: 6px;
  font-size: 12px;
  color: #6b7280;
}

.msg-final-summary {
  line-height: 1.75;
}
</style>
