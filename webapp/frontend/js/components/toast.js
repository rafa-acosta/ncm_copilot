import { el } from "../dom.js";

let stack = null;

function ensureStack() {
  if (!stack) {
    stack = el("div", { class: "toast-stack", role: "status", "aria-live": "polite" });
    document.body.appendChild(stack);
  }
  return stack;
}

export function showToast(message, { variant = "default", timeout = 4500 } = {}) {
  const container = ensureStack();
  const variantClass = variant === "default" ? "" : ` toast--${variant}`;
  const toast = el("div", { class: `toast${variantClass}` }, [el("span", { text: message })]);
  container.appendChild(toast);
  const remove = () => toast.remove();
  if (timeout) setTimeout(remove, timeout);
  toast.addEventListener("click", remove);
  return remove;
}

export const toastSuccess = (msg, opts) => showToast(msg, { ...opts, variant: "success" });
export const toastWarning = (msg, opts) => showToast(msg, { ...opts, variant: "warning" });
export const toastError = (msg, opts) => showToast(msg, { ...opts, variant: "danger", timeout: 7000 });
