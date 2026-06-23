import { safeGet, safePost } from "./client.js";

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
