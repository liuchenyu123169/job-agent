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
