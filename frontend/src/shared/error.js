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
