<script setup>
defineProps({
  modelValue: { type: String, default: "" },
  running: { type: Boolean, default: false },
  switchView: { type: Function, default: null },
});

const emit = defineEmits(["update:modelValue", "send", "cancel"]);

function quickSend(text) {
  emit("update:modelValue", text);
  emit("send");
}
</script>

<template>
  <div class="chat-input-bar">
    <div class="quick-actions">
      <button class="btn btn-ghost btn-small" @click="switchView?.('resume')">📄 简历管理</button>
      <button class="btn btn-ghost btn-small" @click="switchView?.('job')">💼 新建岗位</button>
      <button class="btn btn-ghost btn-small" :disabled="running" @click="quickSend('全面备战')">
        🎯 一键备战
      </button>
    </div>

    <div class="input-row">
      <input
        :value="modelValue"
        type="text"
        class="chat-input"
        placeholder="输入你的需求，例如：帮我全面备战这个岗位"
        :disabled="running"
        @input="emit('update:modelValue', $event.target.value)"
        @keyup.enter="emit('send')"
      />
      <button
        class="btn btn-primary"
        :disabled="running || !modelValue.trim()"
        @click="emit('send')"
      >
        发送
      </button>
      <button v-if="running" class="btn btn-secondary" @click="emit('cancel')">取消</button>
    </div>
  </div>
</template>
