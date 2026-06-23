<script setup>
import { inject, reactive, ref } from "vue";
import { getErrorMessage } from "../shared/error.js";

const api = inject("api");
const setMessage = inject("setMessage");
const loadingMap = inject("loadingMap");
const token = inject("token");
const currentUser = inject("currentUser");
const fetchResumeList = inject("fetchResumeList");
const fetchJobList = inject("fetchJobList");
const fetchTasks = inject("fetchTasks");

const emit = defineEmits(["loggedIn"]);

const authMode = ref("login");
const authForm = reactive({ username: "", password: "" });

async function submit() {
  if (!authForm.username || !authForm.password) { setMessage("请输入用户名和密码。", true); return; }
  loadingMap.auth = true;
  try {
    const resp = authMode.value === "register"
      ? await api.authApi.register(authForm.username, authForm.password)
      : await api.authApi.login(authForm.username, authForm.password);
    token.value = resp.access_token;
    localStorage.setItem("token", resp.access_token);
    currentUser.value = { id: resp.user_id, username: resp.username };
    authForm.username = ""; authForm.password = "";
    emit("loggedIn");
    await Promise.all([fetchResumeList(), fetchJobList(), fetchTasks()]);
  } catch (err) { setMessage(getErrorMessage(err), true); }
  finally { loadingMap.auth = false; }
}
</script>

<template>
  <div class="auth-shell">
    <div class="auth-card">
      <div class="auth-brand">
        <div class="brand-mark">JA</div>
        <div><h1>JobAgent</h1><p>AI 求职助手</p></div>
      </div>
      <div class="auth-switch">
        <button class="auth-tab" :class="{ active: authMode === 'login' }" @click="authMode = 'login'">登录</button>
        <button class="auth-tab" :class="{ active: authMode === 'register' }" @click="authMode = 'register'">注册</button>
      </div>
      <div class="form-stack">
        <label class="field"><span>用户名</span><input v-model="authForm.username" type="text" placeholder="请输入用户名" /></label>
        <label class="field"><span>密码</span><input v-model="authForm.password" type="password" placeholder="请输入密码" @keyup.enter="submit" /></label>
      </div>
      <button class="btn btn-primary btn-block" :disabled="loadingMap.auth" @click="submit">
        {{ loadingMap.auth ? "处理中..." : authMode === "login" ? "登录" : "注册并进入" }}
      </button>
    </div>
  </div>
</template>
