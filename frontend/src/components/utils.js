/* 共享工具函数，从 App.vue 抽取出来供所有组件使用 */

/* ── 数组/JSON 规范化 ── */

export function normalizeToArray(value) {
  if (Array.isArray(value)) return value.filter(Boolean);
  if (typeof value === "string" && value.trim()) return [value.trim()];
  return [];
}

export function formatJson(value) {
  if (value === undefined || value === null || value === "") return "暂无内容";
  try { return JSON.stringify(value, null, 2); } catch { return String(value); }
}

export function findFirstValue(source, keys) {
  if (!source || typeof source !== "object") return null;
  for (const key of keys) {
    const v = source[key];
    if (v !== undefined && v !== null && v !== "") return v;
  }
  return null;
}

export function getMatchScore(source) {
  const raw = findFirstValue(source, ["match_score", "score"]);
  if (raw === null) return 0;
  const matched = String(raw).match(/\d+/);
  const score = matched ? Number(matched[0]) : Number(raw);
  return Number.isNaN(score) ? 0 : Math.max(0, Math.min(100, score));
}

/* ── 错误处理 ── */

import axios from "axios";
export function getErrorMessage(err) {
  if (axios.isAxiosError(err)) return err.response?.data?.detail || err.message || "请求失败";
  return err?.message || "请求失败";
}

/* ── 异步 loading 包装器 ── */

/**
 * 高阶函数：封装 setLoading / try / catch / finally 模板。
 * 用法：await withLoading(loadingMap, "key", async () => { ... })
 */
export async function withLoading(loadingMap, key, fn) {
  loadingMap[key] = true;
  try { return await fn(); }
  catch (err) { throw err; }
  finally { loadingMap[key] = false; }
}
