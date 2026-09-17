import { el } from "../dom.js";

// Readable error message up front; raw exception detail only inside a
// collapsed <details> - never shown to the user by default (spec: no raw
// tracebacks in the main UI).
export function errorPanel(err, { title = "Something went wrong" } = {}) {
  const detail = err && err.detail ? err.detail : String(err);
  const technical = err && err.technical ? err.technical : null;

  const children = [el("strong", { text: title }), el("p", { text: detail, style: "margin: 6px 0 0 0;" })];
  if (technical) {
    children.push(
      el("details", {}, [el("summary", { text: "Technical details" }), el("pre", { text: technical })])
    );
  }
  return el("div", { class: "error-panel", role: "alert" }, children);
}
