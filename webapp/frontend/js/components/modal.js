import { el } from "../dom.js";

// Confirmation dialog for every destructive/important action (delete,
// restore default, discard changes) - never a browser confirm()/alert().
export function confirmDialog({ title, body, confirmLabel = "Confirm", danger = false, requireTypedValue = null }) {
  return new Promise((resolve) => {
    let typedOk = !requireTypedValue;
    const confirmBtn = el("button", {
      class: `btn ${danger ? "btn--danger" : "btn--primary"}`,
      text: confirmLabel,
      disabled: requireTypedValue ? "disabled" : null,
      onclick: () => {
        close();
        resolve(true);
      },
    });

    const bodyChildren = [el("p", { class: "modal__body", text: body })];
    if (requireTypedValue) {
      const input = el("input", {
        class: "input",
        placeholder: requireTypedValue,
        oninput: (e) => {
          typedOk = e.target.value === requireTypedValue;
          confirmBtn.disabled = !typedOk;
        },
      });
      bodyChildren.push(
        el("p", { class: "field__hint", text: `Type "${requireTypedValue}" to confirm.` }),
        input
      );
    }

    const overlay = el(
      "div",
      { class: "modal-overlay", role: "dialog", "aria-modal": "true" },
      [
        el("div", { class: "modal" }, [
          el("h3", { class: "modal__title", text: title }),
          ...bodyChildren,
          el("div", { class: "modal__actions" }, [
            el("button", {
              class: "btn",
              text: "Cancel",
              onclick: () => {
                close();
                resolve(false);
              },
            }),
            confirmBtn,
          ]),
        ]),
      ]
    );

    function close() {
      overlay.remove();
      document.removeEventListener("keydown", onKeydown);
    }
    function onKeydown(e) {
      if (e.key === "Escape") {
        close();
        resolve(false);
      }
    }
    document.addEventListener("keydown", onKeydown);
    document.body.appendChild(overlay);
    (requireTypedValue ? overlay.querySelector("input") : confirmBtn).focus();
  });
}

export function openModal({ title, bodyNode, wide = false }) {
  const overlay = el(
    "div",
    { class: "modal-overlay", role: "dialog", "aria-modal": "true" },
    [
      el("div", { class: `modal${wide ? " modal--wide" : ""}` }, [
        el("div", { class: "cluster", style: "justify-content:space-between; margin-bottom: 12px;" }, [
          el("h3", { class: "modal__title", text: title, style: "margin:0;" }),
          el("button", { class: "btn-icon", "aria-label": "Close", text: "✕", onclick: () => close() }),
        ]),
        bodyNode,
      ]),
    ]
  );
  function close() {
    overlay.remove();
    document.removeEventListener("keydown", onKeydown);
  }
  function onKeydown(e) {
    if (e.key === "Escape") close();
  }
  document.addEventListener("keydown", onKeydown);
  document.body.appendChild(overlay);
  return close;
}
