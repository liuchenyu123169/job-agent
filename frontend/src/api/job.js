import { safeGet, safePost } from "./client.js";

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
  },
};
