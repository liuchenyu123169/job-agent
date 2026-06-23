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
