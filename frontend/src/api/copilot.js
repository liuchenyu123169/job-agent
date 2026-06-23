import { request, safeGet } from "./client.js";

function _dispatchCopilotEvent(event, data, callbacks) {
  console.log("[SSE→C", event, new Date().toISOString().slice(11, 23), data);
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
      console.warn("[SSE→C unknown event type:", event);
      break;
  }
}

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
  return currentEvent;
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
      const responseSessionId = response.headers.get("X-Session-Id");
      if (responseSessionId) {
        callbacks.onSessionCreated?.(Number(responseSessionId));
      }

      if (!response.ok) {
        const text = await response.text();
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
      let currentEvent = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) {
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
