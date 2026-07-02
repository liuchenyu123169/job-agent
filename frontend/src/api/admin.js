import { request, safeGet } from "./client.js";

export const adminApi = {
  listUsers() {
    return safeGet("/api/admin/users", undefined, "listUsers");
  },
  updateUser(userId, data) {
    return request.put(`/api/admin/users/${userId}`, data);
  },
  deleteUser(userId) {
    return request.delete(`/api/admin/users/${userId}`);
  },
  listAllResumes(params) {
    return safeGet("/api/admin/resumes", { params }, "listAllResumes");
  },
  listAllJobs(params) {
    return safeGet("/api/admin/jobs", { params }, "listAllJobs");
  },
  listAllTasks(params) {
    return safeGet("/api/admin/tasks", { params }, "listAllTasks");
  },
  listAllSessions(params) {
    return safeGet("/api/admin/sessions", { params }, "listAllSessions");
  },
  listTraces(params) {
    return safeGet("/api/admin/traces", { params }, "listTraces");
  },
  getStats() {
    return safeGet("/api/admin/stats", undefined, "getStats");
  },
};
