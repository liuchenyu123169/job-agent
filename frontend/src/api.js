import axios from "axios";

const request = axios.create({
  baseURL: "http://127.0.0.1:8000"
});

export async function uploadResume(file) {
  const formData = new FormData();
  formData.append("file", file);
  const { data } = await request.post("/api/resume/upload", formData, {
    headers: {
      "Content-Type": "multipart/form-data"
    }
  });
  return data;
}

export async function createJob(payload) {
  const { data } = await request.post("/api/job", payload);
  return data;
}

export async function analyzeMatch(payload) {
  const { data } = await request.post("/api/agent/analyze", payload);
  return data;
}

export async function optimizeResume(payload) {
  const { data } = await request.post("/api/agent/optimize-resume", payload);
  return data;
}

export async function generateInterviewQuestions(payload) {
  const { data } = await request.post("/api/agent/generate-interview-questions", payload);
  return data;
}
