import { safeGet } from "./client.js";

export const taskApi = {
  listTasks(params = {}) {
    return safeGet("/api/task", { params }, "listTasks");
  },
  getTask(taskId) {
    return safeGet(`/api/task/${taskId}`, undefined, "getTask");
  }
};
