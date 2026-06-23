import axios from "axios";

export const request = axios.create({
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

export async function safePost(url, payload, label = url) {
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

export async function safeGet(url, config, label = url) {
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

export async function uploadForm(url, formData, config, label = url) {
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
