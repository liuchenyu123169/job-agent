import { safeGet, uploadForm } from "./client.js";

export const resumeApi = {
  async uploadResume(file) {
    const formData = new FormData();
    formData.append("file", file);
    return uploadForm(
      "/api/resume/upload",
      formData,
      {
        headers: {
          "Content-Type": "multipart/form-data",
        },
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
  },
};
