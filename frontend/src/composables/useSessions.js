import { nextTick, ref } from "vue";

export function useSessions({
  activeView,
  adminMode,
  chatRef,
  copilotApi,
  currentUser,
  getErrorMessage,
  setMessage,
}) {
  const currentSessionId = ref(getStoredSessionId());
  const sessions = ref([]);
  const sessionsExpanded = ref(true);

  function getStoredSessionId() {
    const stored = localStorage.getItem("currentSessionId");
    return stored ? Number(stored) : null;
  }

  function storeSessionId(id) {
    currentSessionId.value = id;
    localStorage.setItem("currentSessionId", String(id));
  }

  async function loadSessions() {
    try {
      sessions.value = await copilotApi.listSessions(20);
    } catch {
      // silent
    }
  }

  async function selectSession(sessionId) {
    currentSessionId.value = sessionId;
    storeSessionId(sessionId);
    if (!adminMode.value) activeView.value = "chat";
    await nextTick();
    if (chatRef.value) {
      await chatRef.value.loadSessionHistory(sessionId);
    }
  }

  async function newChat() {
    currentSessionId.value = null;
    localStorage.removeItem("currentSessionId");
    if (!adminMode.value) activeView.value = "chat";
    await nextTick();
    if (chatRef.value) {
      await chatRef.value.resetForNewChat(currentUser.value?.username || "");
    }
  }

  async function deleteSession(sessionId, event) {
    event.stopPropagation();
    if (!confirm("确认删除此对话？")) return;
    try {
      await copilotApi.deleteSession(sessionId);
      if (currentSessionId.value === sessionId) {
        await newChat();
      }
      await loadSessions();
    } catch (err) {
      setMessage(getErrorMessage(err), true);
    }
  }

  function truncateGoal(goal, maxLen = 18) {
    if (!goal) return "新对话";
    return goal.length > maxLen ? goal.slice(0, maxLen) + "..." : goal;
  }

  return {
    currentSessionId,
    deleteSession,
    loadSessions,
    newChat,
    selectSession,
    sessions,
    sessionsExpanded,
    storeSessionId,
    truncateGoal,
  };
}
