import { marked } from "marked";

// marked 配置：换行 → <br>，启用 GFM（表格/删除线/任务列表等）
marked.setOptions({ breaks: true, gfm: true });

export function renderMarkdown(text) {
  if (!text) return "";
  // 标题降级：# → h2, ## → h3, ### → h4（h1 留给页面标题）
  const downgraded = text.replace(/^### (.+)$/gm, "#### $1")
                        .replace(/^## (.+)$/gm, "### $1")
                        .replace(/^# (.+)$/gm, "## $1");
  return marked.parse(downgraded);
}
