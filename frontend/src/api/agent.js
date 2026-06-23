import { safePost } from "./client.js";

export const agentApi = {
  recommendJobs(payload) {
    return safePost("/api/agent/recommend-jobs", payload, "recommendJobs");
  }
};
