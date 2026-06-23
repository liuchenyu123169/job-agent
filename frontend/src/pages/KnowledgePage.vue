<script setup>
import { inject, ref } from "vue";

const api = inject("api");
const setMessage = inject("setMessage");
const loadingMap = inject("loadingMap");

const buildResult = ref(null);
const searchQuery = ref("");
const topK = ref(5);
const searchResult = ref(null);

async function buildKnowledge() {
  loadingMap.knowledgeBuild = true;
  try {
    buildResult.value = await api.knowledgeApi.buildKnowledge();
    setMessage("知识库构建完成。");
  } catch (err) { setMessage(err?.message || "构建失败", true); }
  finally { loadingMap.knowledgeBuild = false; }
}

async function searchKnowledge() {
  if (!searchQuery.value.trim()) { setMessage("请输入检索内容。", true); return; }
  loadingMap.knowledgeSearch = true;
  try {
    searchResult.value = await api.knowledgeApi.searchKnowledge(searchQuery.value.trim(), Number(topK.value) || 5);
  } catch (err) { setMessage(err?.message || "检索失败", true); }
  finally { loadingMap.knowledgeSearch = false; }
}
</script>

<template>
  <button class="btn btn-primary btn-block" :disabled="loadingMap.knowledgeBuild" @click="buildKnowledge">
    {{ loadingMap.knowledgeBuild ? "构建中..." : "构建知识库" }}
  </button>
  <div v-if="buildResult" class="info-list section-top">
    <div class="info-item"><span>文件数</span><strong>{{ buildResult.file_count }}</strong></div>
    <div class="info-item"><span>切片数</span><strong>{{ buildResult.chunk_count }}</strong></div>
  </div>
  <hr />
  <div class="form-stack">
    <label class="field"><span>Query</span><input v-model="searchQuery" placeholder="如 Spring Boot 面试题" /></label>
    <label class="field"><span>Top K</span><input v-model="topK" type="number" min="1" max="20" /></label>
    <button class="btn btn-secondary" :disabled="loadingMap.knowledgeSearch" @click="searchKnowledge">检索</button>
  </div>
  <div v-if="searchResult?.items?.length" class="result-list section-top">
    <div v-for="(item, idx) in searchResult.items" :key="idx" class="result-card">
      <h5>{{ item.title || "知识片段" }}</h5>
      <small>{{ item.source }}</small>
      <p>{{ item.clean_content || item.content || "" }}</p>
    </div>
  </div>
</template>
