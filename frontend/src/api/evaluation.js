import { safeGet, safePost } from "./client.js";

export const evaluationApi = {
  runEvaluation(payload) {
    return safePost("/api/evaluation/run", payload, "runEvaluation");
  },
  listWorkflows() {
    return safeGet("/api/evaluation/workflows", undefined, "listEvaluationWorkflows");
  },
  listResults() {
    return safeGet("/api/evaluation/results", undefined, "listEvaluationResults");
  },
};
