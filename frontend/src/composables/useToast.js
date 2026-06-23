import { ref } from "vue";

export function useToast() {
  const message = ref("");
  const error = ref("");
  const toastVisible = ref(false);
  let toastTimer = null;

  function setMessage(text, isError = false) {
    clearTimeout(toastTimer);
    if (isError) {
      error.value = text;
      message.value = "";
    } else {
      message.value = text;
      error.value = "";
    }
    toastVisible.value = true;
    toastTimer = setTimeout(() => {
      toastVisible.value = false;
      message.value = "";
      error.value = "";
    }, 3000);
  }

  return {
    error,
    message,
    setMessage,
    toastVisible,
  };
}
