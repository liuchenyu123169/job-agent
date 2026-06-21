/* 共享工具函数，从 App.vue 抽取出来供所有组件使用 */

/* ── 数组/JSON 规范化 ── */

export const COPILOT_REPORT_MARKER = "__COPILOT_REPORT__";

export function normalizeToArray(value) {
  if (Array.isArray(value)) return value.filter(Boolean);
  if (typeof value === "string" && value.trim()) return [value.trim()];
  return [];
}

/** 规范化 output_json 中的数组字段（供 preNormalize 和 parsedOutput 共用） */
export function normalizeOutputFields(out) {
  if (!out || typeof out !== "object") return out;
  const result = { ...out };
  const analysis = { ...(result.analysis || {}) };
  ["advantages", "weaknesses", "suggestions"].forEach(k => {
    if (analysis[k] !== undefined) analysis[k] = normalizeToArray(analysis[k]);
  });
  if (Object.keys(analysis).length) result.analysis = analysis;
  const optimization = { ...(result.optimization || {}) };
  ["skill_keywords", "project_suggestions", "resume_rewrite_suggestions", "risk_points"].forEach(k => {
    if (optimization[k] !== undefined) optimization[k] = normalizeToArray(optimization[k]);
  });
  if (Object.keys(optimization).length) result.optimization = optimization;
  const questions = { ...(result.questions || {}) };
  ["technical_questions", "project_questions", "behavior_questions", "risk_questions"].forEach(k => {
    if (questions[k] !== undefined) questions[k] = normalizeToArray(questions[k]);
  });
  if (Object.keys(questions).length) result.questions = questions;
  return result;
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
  if (axios.isAxiosError(err)) {
    const detail = err.response?.data?.detail;
    if (!detail) return err.message || "请求失败";
    // Pydantic 验证错误返回数组 [{msg, loc, type}, ...]
    if (Array.isArray(detail)) {
      const first = detail[0];
      if (first?.msg) return first.msg.replace(/^Value error, /, "");
      return JSON.stringify(detail[0]);
    }
    return String(detail);
  }
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

/* ── Markdown → HTML（ChatPanel 和 AdminTasks 共用） ── */

function _inline(s) {
  s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
  s = s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  return s;
}

export function renderMarkdown(text) {
  if (!text) return "";
  text = text.replace(/([^\n])(\*\*[^*]+\*\*[：:])/g, "$1\n$2");
  const lines = text.split("\n");
  const out = [];
  let inUl = false, inOl = false;
  function closeLists() {
    if (inUl) { out.push("</ul>"); inUl = false; }
    if (inOl) { out.push("</ol>"); inOl = false; }
  }
  function peekNonEmpty(from) {
    for (let j = from; j < lines.length; j++) {
      if (lines[j].trim()) return lines[j].trim();
    }
    return null;
  }
  for (let i = 0; i < lines.length; i++) {
    const trimmed = lines[i].trim();
    if (!trimmed) {
      const next = peekNonEmpty(i + 1);
      if (inOl && next && /^\d+[\.\)]\s/.test(next)) continue;
      if (inUl && next && /^[\-\*]\s(?!\*)/.test(next)) continue;
      closeLists();
      continue;
    }
    const headMatch = trimmed.match(/^(#{1,4})\s+(.+)/);
    if (headMatch) {
      closeLists();
      const level = Math.min(headMatch[1].length + 1, 5);
      out.push("<h" + level + ">" + _inline(headMatch[2]) + "</h" + level + ">");
      continue;
    }
    const ulMatch = trimmed.match(/^[\-\*]\s(?!\*)(.+)/);
    if (ulMatch) {
      if (inOl) { out.push("</ol>"); inOl = false; }
      if (!inUl) { out.push("<ul>"); inUl = true; }
      out.push("<li>" + _inline(ulMatch[1]) + "</li>");
      continue;
    }
    const olMatch = trimmed.match(/^\d+[\.\)]\s+(.+)/);
    if (olMatch) {
      if (inUl) { out.push("</ul>"); inUl = false; }
      if (!inOl) { out.push("<ol>"); inOl = true; }
      out.push("<li>" + _inline(olMatch[1]) + "</li>");
      continue;
    }
    closeLists();
    out.push("<p>" + _inline(trimmed) + "</p>");
  }
  closeLists();
  return out.join("");
}
