import axios from "axios";

const request = axios.create({
  baseURL: "http://127.0.0.1:8000"
});

let unauthorizedHandler = null;

export function setUnauthorizedHandler(handler) {
  unauthorizedHandler = handler;
}

request.interceptors.request.use((config) => {
  const token = localStorage.getItem("token");
  if (token) {
    config.headers = config.headers || {};
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

request.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem("token");
      if (typeof unauthorizedHandler === "function") {
        unauthorizedHandler();
      }
    }
    return Promise.reject(error);
  }
);

function logRequest(label, payload) {
  console.log(`[API] ${label} request`, payload);
}

function logResponse(label, response) {
  console.log(`[API] ${label} response`, response);
}

function logFailure(label, error) {
  console.error(`[API] ${label} failed`, error.response?.data || error);
}

async function safePost(url, payload, label = url) {
  logRequest(label, payload);
  try {
    const { data } = await request.post(url, payload);
    logResponse(label, data);
    return data;
  } catch (error) {
    logFailure(label, error);
    throw error;
  }
}

async function safeGet(url, config, label = url) {
  logRequest(label, config?.params || {});
  try {
    const { data } = await request.get(url, config);
    logResponse(label, data);
    return data;
  } catch (error) {
    logFailure(label, error);
    throw error;
  }
}

async function uploadForm(url, formData, config, label = url) {
  logRequest(label, { file: formData.get("file")?.name || null });
  try {
    const { data } = await request.post(url, formData, config);
    logResponse(label, data);
    return data;
  } catch (error) {
    logFailure(label, error);
    throw error;
  }
}

export const authApi = {
  register(username, password) {
    return safePost("/api/auth/register", { username, password }, "register");
  },
  login(username, password) {
    return safePost("/api/auth/login", { username, password }, "login");
  },
  getCurrentUser() {
    return safeGet("/api/auth/me", undefined, "getCurrentUser");
  }
};

export const resumeApi = {
  async uploadResume(file) {
    const formData = new FormData();
    formData.append("file", file);
    return uploadForm(
      "/api/resume/upload",
      formData,
      {
        headers: {
          "Content-Type": "multipart/form-data"
        }
      },
      "uploadResume"
    );
  },
  getResume(resumeId) {
    return safeGet(`/api/resume/${resumeId}`, undefined, "getResume");
  },
  getResumeByLocalId(localResumeId) {
    return safeGet(`/api/resume/local/${localResumeId}`, undefined, "getResumeByLocalId");
  },
  listResumes() {
    return safeGet("/api/resume", undefined, "listResumes");
  }
};

export const jobApi = {
  createJob(payload) {
    return safePost("/api/job", payload, "createJob");
  },
  getJob(jobId) {
    return safeGet(`/api/job/${jobId}`, undefined, "getJob");
  },
  getJobByLocalId(localJobId) {
    return safeGet(`/api/job/local/${localJobId}`, undefined, "getJobByLocalId");
  },
  listJobs() {
    return safeGet("/api/job", undefined, "listJobs");
  }
};

export const agentApi = {
  analyze(payload) {
    return safePost("/api/agent/analyze", payload, "analyze");
  },
  optimizeResume(payload) {
    return safePost("/api/agent/optimize-resume", payload, "optimizeResume");
  },
  generateInterviewQuestions(payload) {
    return safePost(
      "/api/agent/generate-interview-questions",
      payload,
      "generateInterviewQuestions"
    );
  },
  recommendJobs(payload) {
    return safePost("/api/agent/recommend-jobs", payload, "recommendJobs");
  }
};

export const knowledgeApi = {
  buildKnowledge() {
    return safePost("/api/knowledge/build", {}, "buildKnowledge");
  },
  searchKnowledge(query, topK = 5) {
    return safeGet(
      "/api/knowledge/search",
      {
        params: {
          query,
          top_k: topK
        }
      },
      "searchKnowledge"
    );
  }
};

export const taskApi = {
  listTasks(params = {}) {
    return safeGet("/api/task", { params }, "listTasks");
  },
  getTask(taskId) {
    return safeGet(`/api/task/${taskId}`, undefined, "getTask");
  }
};

// ── Copilot SSE 流式调用 ──

function _parseSSELines(lines, currentEvent, callbacks) {
  for (const line of lines) {
    if (line.startsWith("event: ")) {
      currentEvent = line.slice(7).trim();
    } else if (line.startsWith("data: ")) {
      try {
        _dispatchCopilotEvent(currentEvent, JSON.parse(line.slice(6)), callbacks);
      } catch (e) {
        console.warn("[SSE] parse error", currentEvent, e);
      }
      currentEvent = "";
    }
  }
  return currentEvent;  // 返回给调用方，跨 chunk 保持
}

export function streamCopilot(payload, callbacks) {
  const token = localStorage.getItem("token");
  if (!token) {
    callbacks.onError?.("未登录");
    return () => {};
  }

  const controller = new AbortController();

  fetch("http://127.0.0.1:8000/api/copilot/run", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(payload),
    signal: controller.signal,
  })
    .then(async (response) => {
      // 立即从响应头读取 session_id 并持久化（不等 final 事件）
      const responseSessionId = response.headers.get("X-Session-Id");
      if (responseSessionId) {
        callbacks.onSessionCreated?.(Number(responseSessionId));
      }

      if (!response.ok) {
        const text = await response.text();
        // 会话过期/被删除 → 自动清除 session_id 并重试（最多一次）
        if (response.status === 404 && payload.session_id && !payload._retried) {
          if (text.includes("Session not found")) {
            console.warn("[API] stale session_id=%s, auto-clearing and retrying", payload.session_id);
            localStorage.removeItem("currentSessionId");
            const retryPayload = { ...payload, session_id: undefined, _retried: true };
            streamCopilot(retryPayload, callbacks);
            return;
          }
        }
        callbacks.onError?.(text || `HTTP ${response.status}`);
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let currentEvent = "";  // ⚠️ 闭包保持跨 chunk 状态

      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          // 流结束，flush 缓冲区残留数据
          if (buffer.trim()) {
            _parseSSELines(buffer.split("\n"), currentEvent, callbacks);
          }
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        currentEvent = _parseSSELines(lines, currentEvent, callbacks);
      }
    })
    .catch((err) => {
      if (err.name !== "AbortError") {
        callbacks.onError?.(err.message || "网络错误");
      }
    });

  return () => controller.abort();
}

function _dispatchCopilotEvent(event, data, callbacks) {
  console.log("[SSE←]", event, new Date().toISOString().slice(11, 23), data);
  switch (event) {
    case "plan":
      callbacks.onPlan?.(data);
      break;
    case "step_start":
      callbacks.onStepStart?.(data);
      break;
    case "step_progress":
      callbacks.onStepProgress?.(data);
      break;
    case "step_complete":
      callbacks.onStepComplete?.(data);
      break;
    case "error":
      callbacks.onStepError?.(data);
      break;
    case "step_token":
      callbacks.onStepToken?.(data);
      break;
    case "final":
      callbacks.onFinal?.(data);
      break;
    default:
      console.warn("[SSE←] unknown event type:", event);
      break;
  }
}

export const copilotApi = {
  streamRun(payload, callbacks) {
    return streamCopilot(payload, callbacks);
  },
  listTools() {
    return safeGet("/api/copilot/tools", undefined, "listTools");
  },
  listSkills() {
    return safeGet("/api/copilot/skills", undefined, "listSkills");
  },
  listSessions(limit = 20) {
    return safeGet("/api/copilot/sessions", { params: { limit } }, "listSessions");
  },
  getSession(sessionId) {
    return safeGet(`/api/copilot/sessions/${sessionId}`, undefined, "getSession");
  },
  getSessionMessages(sessionId) {
    return safeGet(`/api/copilot/sessions/${sessionId}/messages`, undefined, "getSessionMessages");
  },
  deleteSession(sessionId) {
    return request.delete(`/api/copilot/sessions/${sessionId}`);
  },
};

export const adminApi = {
  listUsers() { return safeGet("/api/admin/users", undefined, "listUsers"); },
  updateUser(userId, data) { return request.put(`/api/admin/users/${userId}`, data); },
  deleteUser(userId) { return request.delete(`/api/admin/users/${userId}`); },
  listAllResumes(params) { return safeGet("/api/admin/resumes", { params }, "listAllResumes"); },
  listAllJobs(params) { return safeGet("/api/admin/jobs", { params }, "listAllJobs"); },
  listAllTasks(params) { return safeGet("/api/admin/tasks", { params }, "listAllTasks"); },
  listAllSessions(params) { return safeGet("/api/admin/sessions", { params }, "listAllSessions"); },
  listTraces(params) { return safeGet("/api/admin/traces", { params }, "listTraces"); },
  getStats() { return safeGet("/api/admin/stats", undefined, "getStats"); },
};
