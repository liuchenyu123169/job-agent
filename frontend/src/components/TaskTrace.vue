<script setup>
const props = defineProps({ trace: { type: Array, default: () => [] } });

function maxDuration() {
  return Math.max(...props.trace.map((s) => s.duration_ms || 0), 1);
}
</script>

<template>
  <div v-if="trace.length" class="trace-section section-top">
    <h5>执行链路</h5>
    <div class="trace-timeline">
      <div v-for="span in trace" :key="span.span_id" class="trace-row">
        <span class="trace-name">{{ span.name }}</span>
        <div class="trace-bar-wrap">
          <div
            class="trace-bar"
            :style="{ width: Math.max((span.duration_ms / maxDuration()) * 100, 1) + '%' }"
          ></div>
        </div>
        <span class="trace-duration">{{ span.duration_ms }}ms</span>
        <span v-if="span.metadata?.tokens_in" class="trace-meta"
          >in:{{ span.metadata.tokens_in }} out:{{ span.metadata.tokens_out }}</span
        >
        <span v-if="span.metadata?.model" class="trace-meta">{{ span.metadata.model }}</span>
      </div>
    </div>
    <div class="trace-total">总计: {{ trace.reduce((s, x) => s + (x.duration_ms || 0), 0) }}ms</div>
  </div>
</template>

<style scoped>
.trace-timeline {
  margin-top: 8px;
}
.trace-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  font-size: 12px;
}
.trace-name {
  width: 120px;
  color: #334155;
  flex-shrink: 0;
}
.trace-bar-wrap {
  flex: 1;
  height: 10px;
  background: #f1f5f9;
  border-radius: 5px;
  overflow: hidden;
}
.trace-bar {
  height: 100%;
  background: #2563eb;
  border-radius: 5px;
  min-width: 2px;
}
.trace-duration {
  width: 50px;
  text-align: right;
  color: #64748b;
  flex-shrink: 0;
}
.trace-meta {
  color: #94a3b8;
  font-size: 10px;
}
.trace-total {
  text-align: right;
  font-size: 12px;
  color: #64748b;
  margin-top: 8px;
  padding-top: 6px;
  border-top: 1px solid #e5e7eb;
}
</style>
