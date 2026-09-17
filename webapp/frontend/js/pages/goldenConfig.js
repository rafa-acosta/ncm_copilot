import { api } from "../api.js";
import { el, clear } from "../dom.js";
import { errorPanel } from "../components/errorPanel.js";
import { toastSuccess, toastError } from "../components/toast.js";
import { confirmDialog, openModal } from "../components/modal.js";
import { getState, setState } from "../state.js";

function humanize(name) {
  return name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function promptText({ title, label, initial = "", confirmLabel = "Save" }) {
  return new Promise((resolve) => {
    const input = el("input", { class: "input", value: initial });
    let close;
    const actions = el("div", { class: "modal__actions" }, [
      el("button", { class: "btn", text: "Cancel", onclick: () => { close(); resolve(null); } }),
      el("button", {
        class: "btn btn--primary", text: confirmLabel,
        onclick: () => { const v = input.value.trim(); close(); resolve(v || null); },
      }),
    ]);
    const body = el("div", { class: "stack" }, [
      el("label", { class: "field__label", text: label }),
      input,
      actions,
    ]);
    close = openModal({ title, bodyNode: body });
    input.focus();
  });
}

export async function render(container) {
  clear(container);

  container.appendChild(
    el("div", { class: "page-header" }, [
      el("div", { class: "page-header__heading" }, [
        el("h1", { text: "Golden Config Manager" }),
        el("p", { text: "Define the baseline every device configuration is audited against." }),
      ]),
    ])
  );

  const loadingBox = el("div", { class: "skeleton skeleton--block" });
  container.appendChild(loadingBox);

  let schema, profiles;
  try {
    [schema, profiles] = await Promise.all([
      api.get("/api/golden/schema"),
      api.get("/api/golden/profiles"),
    ]);
  } catch (err) {
    clear(container);
    container.appendChild(errorPanel(err, { title: "Unable to load Golden Config Manager" }));
    return () => {};
  }
  loadingBox.remove();

  const persisted = getState().activeGoldenProfileId;
  let activeId =
    persisted && profiles.some((p) => p.profile_id === persisted)
      ? persisted
      : (profiles.find((p) => !p.read_only) || profiles[0]).profile_id;

  let profile = null;
  let formVars = {};
  let initialVarsJSON = "{}";
  let previewRawText = "";
  let previewTimer = null;
  let saveBtnRef = null;

  const toolbar = el("div", { class: "card" });
  const dirtyBadge = el("span", { class: "badge badge--warning", text: "Unsaved changes", style: "display:none;" });
  const columns = el("div", { class: "split-layout" });
  const formPane = el("div", { class: "card" });
  const previewPane = el("div", { class: "card" });
  columns.appendChild(formPane);
  columns.appendChild(previewPane);

  container.appendChild(toolbar);
  container.appendChild(columns);

  function isDirty() {
    return JSON.stringify(formVars) !== initialVarsJSON;
  }

  function refreshDirtyUI() {
    const dirty = isDirty();
    dirtyBadge.style.display = dirty ? "" : "none";
    if (saveBtnRef) saveBtnRef.disabled = profile.read_only || !dirty;
  }

  function getValue(controlId, name, fallback) {
    const bucket = formVars[controlId];
    const v = bucket ? bucket[name] : undefined;
    return v === undefined ? fallback : v;
  }

  function setValue(controlId, name, value) {
    if (!formVars[controlId]) formVars[controlId] = {};
    formVars[controlId][name] = value;
    schedulePreview();
  }

  function schedulePreview() {
    refreshDirtyUI();
    clearTimeout(previewTimer);
    previewTimer = setTimeout(async () => {
      try {
        const result = await api.post("/api/golden/preview", { device_vars: formVars });
        updatePreview(result.rendered_text, result.missing, result.warnings, result.valid);
      } catch {
        /* a mid-edit preview failure is non-fatal - the last good preview stays visible */
      }
    }, 500);
  }

  function renderField(controlId, field) {
    const disabled = profile.read_only;
    const label = el("label", { class: "field__label", text: humanize(field.name) });

    if (field.json_type === "boolean") {
      const current = !!getValue(controlId, field.name, false);
      const toggle = el("label", { class: "toggle" }, [
        el("input", {
          type: "checkbox", checked: current ? "checked" : null, disabled: disabled ? "disabled" : null,
          onchange: (e) => setValue(controlId, field.name, e.target.checked),
        }),
        el("span", { class: "toggle__track" }),
      ]);
      return el("div", { class: "field cluster" }, [toggle, label]);
    }

    if (field.json_type === "integer") {
      const current = getValue(controlId, field.name, "");
      const input = el("input", {
        class: "input", type: "number", value: current === null ? "" : current, disabled: disabled ? "disabled" : null,
        oninput: (e) => setValue(controlId, field.name, e.target.value === "" ? null : Number(e.target.value)),
      });
      return el("div", { class: "field" }, [label, input]);
    }

    if (field.json_type === "array") {
      return renderArrayField(controlId, field, disabled, label);
    }

    const enumValues = (field.required_shape && field.required_shape.enum) || null;
    const current = getValue(controlId, field.name, "");
    let input;
    if (Array.isArray(enumValues) && enumValues.length) {
      input = el(
        "select",
        { class: "input", disabled: disabled ? "disabled" : null, onchange: (e) => setValue(controlId, field.name, e.target.value) },
        enumValues.map((v) => el("option", { value: v, text: String(v), selected: v === current ? "selected" : null }))
      );
    } else {
      input = el("input", {
        class: "input", type: "text", value: current === null ? "" : current, disabled: disabled ? "disabled" : null,
        oninput: (e) => setValue(controlId, field.name, e.target.value),
      });
    }
    return el("div", { class: "field" }, [label, input]);
  }

  function renderArrayField(controlId, field, disabled, label) {
    const items = (field.required_shape && field.required_shape.items) || {};
    const isObjectItems = items.type === "object" && !!items.properties;
    const list = Array.isArray(getValue(controlId, field.name, [])) ? getValue(controlId, field.name, []) : [];

    const listEl = el("div", { class: "repeat-list" });

    function commit() {
      setValue(controlId, field.name, list);
    }

    function removeBtn(index) {
      return el("button", {
        class: "btn-icon", "aria-label": "Remove row", text: "✕", disabled: disabled ? "disabled" : null,
        onclick: () => { list.splice(index, 1); commit(); renderRows(); },
      });
    }

    function renderRows() {
      clear(listEl);
      list.forEach((row, index) => {
        if (isObjectItems) {
          const subFields = Object.entries(items.properties).map(([subName, subSchema]) => {
            const subType = subSchema.type || "string";
            let subInput;
            if (subType === "boolean") {
              subInput = el("input", {
                type: "checkbox", checked: row[subName] ? "checked" : null, disabled: disabled ? "disabled" : null,
                onchange: (e) => { row[subName] = e.target.checked; commit(); },
              });
            } else if (subType === "integer") {
              subInput = el("input", {
                class: "input", type: "number", value: row[subName] ?? "", disabled: disabled ? "disabled" : null,
                oninput: (e) => { row[subName] = e.target.value === "" ? null : Number(e.target.value); commit(); },
              });
            } else {
              subInput = el("input", {
                class: "input", type: "text", value: row[subName] ?? "", disabled: disabled ? "disabled" : null,
                oninput: (e) => { row[subName] = e.target.value; commit(); },
              });
            }
            return el("div", { class: "field" }, [el("span", { class: "field__hint", text: humanize(subName) }), subInput]);
          });
          listEl.appendChild(
            el("div", { class: "repeat-row" }, [el("div", { class: "repeat-row__fields" }, subFields), removeBtn(index)])
          );
        } else {
          const simpleInput = el("input", {
            class: "input", type: "text", value: typeof row === "string" ? row : String(row ?? ""), disabled: disabled ? "disabled" : null,
            oninput: (e) => { list[index] = e.target.value; commit(); },
          });
          listEl.appendChild(
            el("div", { class: "repeat-row" }, [el("div", { class: "repeat-row__fields" }, [simpleInput]), removeBtn(index)])
          );
        }
      });
    }
    renderRows();

    const addBtn = el("button", {
      class: "btn btn--sm", text: "Add", disabled: disabled ? "disabled" : null,
      onclick: () => { list.push(isObjectItems ? {} : ""); commit(); renderRows(); },
    });

    return el("div", { class: "field" }, [label, listEl, addBtn]);
  }

  function buildForm() {
    clear(formPane);
    formPane.appendChild(el("h3", { text: "Configuration Fields" }));
    if (profile.read_only) {
      formPane.appendChild(
        el("p", { class: "field__hint", text: 'This is the read-only system Default. Use "Save As" to create an editable copy.' })
      );
    }
    const stack = el("div", { class: "stack" });
    for (const spec of schema) {
      const fieldsStack = el("div", { class: "stack" }, spec.fields.map((f) => renderField(spec.control_id, f)));
      stack.appendChild(
        el("div", { class: "card" }, [
          el("h4", { text: `${spec.control_id} — ${spec.title}`, style: "margin-bottom:4px;" }),
          spec.explanation ? el("p", { class: "field__hint", text: spec.explanation, style: "margin-bottom:12px;" }) : null,
          fieldsStack,
        ])
      );
    }
    formPane.appendChild(stack);
  }

  function updatePreview(text, missing, warnings, valid) {
    previewRawText = text;
    clear(previewPane);
    previewPane.appendChild(el("h3", { text: "Live Preview" }));
    if (!valid) {
      previewPane.appendChild(
        el("div", { class: "badge badge--warning", text: "Preview incomplete — see missing values below" })
      );
    }
    const searchInput = el("input", {
      class: "input", placeholder: "Search preview...", style: "margin: var(--space-3) 0;",
      oninput: (e) => renderLines(e.target.value),
    });
    previewPane.appendChild(searchInput);
    const codeBox = el("div", { class: "code-preview" });
    previewPane.appendChild(codeBox);

    function renderLines(filter) {
      clear(codeBox);
      const term = filter.trim().toLowerCase();
      const lines = previewRawText.split("\n");
      const visible = term ? lines.filter((l) => l.toLowerCase().includes(term)) : lines;
      visible.forEach((line) => codeBox.appendChild(el("div", { text: line.length ? line : " " })));
    }
    renderLines("");

    if (missing && missing.length) {
      previewPane.appendChild(
        el("div", { class: "card", style: "margin-top: var(--space-4);" }, [
          el("h4", { text: "Missing Values" }),
          el("ul", {}, missing.map((m) => el("li", { text: m }))),
        ])
      );
    }
    if (warnings && warnings.length) {
      previewPane.appendChild(
        el("div", { class: "card", style: "margin-top: var(--space-4);" }, [
          el("h4", { text: "Warnings" }),
          el("ul", {}, warnings.map((w) => el("li", { text: w }))),
        ])
      );
    }
  }

  function showDiffModal(name, diffLines) {
    const box = el("div", { class: "code-preview", style: "max-height: 60vh;" });
    diffLines.forEach(({ line }) => {
      let cls = "";
      if (line.startsWith("+") && !line.startsWith("+++")) cls = "code-preview__diff-add";
      else if (line.startsWith("-") && !line.startsWith("---")) cls = "code-preview__diff-remove";
      box.appendChild(el("div", { class: cls || null, text: line.length ? line : " " }));
    });
    if (!diffLines.length) box.appendChild(el("div", { text: "No differences — identical to Default." }));
    openModal({ title: `Compare "${name}" with Default`, bodyNode: box, wide: true });
  }

  function renderImportResult(box, result) {
    clear(box);
    box.appendChild(
      el("div", {
        class: `badge ${result.is_valid ? "badge--success" : "badge--danger"}`,
        text: result.is_valid ? "Structure valid — all active control sections present" : "Structure invalid",
      })
    );
    if (result.duplicate_sections.length) {
      box.appendChild(
        el("p", { class: "field__error", text: `Duplicate sections: ${result.duplicate_sections.join(", ")}` })
      );
    }
    if (result.missing_sections.length) {
      box.appendChild(
        el("div", { style: "margin-top: var(--space-3);" }, [
          el("strong", { text: "Missing sections:" }),
          el("ul", {}, result.missing_sections.map((s) => el("li", { text: `${s.control_id} — ${s.title}` }))),
        ])
      );
    }
  }

  function showImportModal() {
    const textarea = el("textarea", {
      class: "input", rows: "14", style: "font-family: var(--font-family-mono); width: 100%;",
      placeholder: "Paste golden config text here, or choose a file below...",
    });
    const fileInput = el("input", {
      type: "file", accept: ".txt",
      onchange: async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        textarea.value = await file.text();
      },
    });
    const resultBox = el("div", { style: "margin-top: var(--space-4);" });
    const validateBtn = el("button", {
      class: "btn btn--primary", text: "Validate Structure",
      onclick: async () => {
        clear(resultBox);
        try {
          const result = await api.post("/api/golden/import", { text: textarea.value });
          renderImportResult(resultBox, result);
        } catch (err) {
          resultBox.appendChild(errorPanel(err, { title: "Unable to validate" }));
        }
      },
    });
    const body = el("div", { class: "stack" }, [
      el("p", {
        class: "field__hint",
        text: "Checks the file's control sections against the active controls list. This is a structural check only — values are not imported into the form.",
      }),
      fileInput,
      textarea,
      validateBtn,
      resultBox,
    ]);
    openModal({ title: "Import Golden Config (.txt)", bodyNode: body, wide: true });
  }

  function buildToolbar() {
    clear(toolbar);

    const select = el(
      "select",
      { class: "input", style: "max-width: 280px;" },
      profiles.map((p) =>
        el("option", { value: p.profile_id, text: p.name + (p.read_only ? " (Default)" : ""), selected: p.profile_id === activeId ? "selected" : null })
      )
    );
    select.addEventListener("change", async (e) => {
      const newId = e.target.value;
      if (isDirty()) {
        const ok = await confirmDialog({
          title: "Discard unsaved changes?",
          body: "Switching profiles will discard your unsaved edits. Continue?",
          confirmLabel: "Discard",
          danger: true,
        });
        if (!ok) {
          select.value = activeId;
          return;
        }
      }
      await loadProfile(newId);
    });

    const newBtn = el("button", {
      class: "btn btn--sm", text: "New Profile",
      onclick: async () => {
        const name = await promptText({ title: "New Golden Config Profile", label: "Profile name" });
        if (!name) return;
        try {
          const created = await api.post("/api/golden/profiles", { name });
          profiles = await api.get("/api/golden/profiles");
          toastSuccess(`Profile "${name}" created.`);
          await loadProfile(created.profile_id);
        } catch (err) {
          toastError(err.detail);
        }
      },
    });

    const saveBtn = el("button", {
      class: "btn btn--primary btn--sm", text: "Save",
      disabled: profile.read_only || !isDirty() ? "disabled" : null,
      onclick: async () => {
        try {
          const result = await api.put(`/api/golden/profiles/${activeId}`, { device_vars: formVars });
          initialVarsJSON = JSON.stringify(formVars);
          toastSuccess("Profile saved.");
          updatePreview(result.rendered_text, result.missing, result.warnings, true);
          refreshDirtyUI();
        } catch (err) {
          toastError(err.detail);
        }
      },
    });
    saveBtnRef = saveBtn;

    const saveAsBtn = el("button", {
      class: "btn btn--sm", text: "Save As",
      onclick: async () => {
        const name = await promptText({ title: "Save As New Profile", label: "New profile name" });
        if (!name) return;
        try {
          const created = await api.post("/api/golden/profiles", { name, device_vars: formVars });
          profiles = await api.get("/api/golden/profiles");
          toastSuccess(`Saved as "${name}".`);
          await loadProfile(created.profile_id);
        } catch (err) {
          toastError(err.detail);
        }
      },
    });

    const duplicateBtn = el("button", {
      class: "btn btn--sm", text: "Duplicate",
      onclick: async () => {
        const name = await promptText({ title: "Duplicate Profile", label: "New profile name", initial: `${profile.name} copy` });
        if (!name) return;
        try {
          const created = await api.post(`/api/golden/profiles/${activeId}/duplicate`, { new_name: name });
          profiles = await api.get("/api/golden/profiles");
          toastSuccess(`Duplicated as "${name}".`);
          await loadProfile(created.profile_id);
        } catch (err) {
          toastError(err.detail);
        }
      },
    });

    const renameBtn = el("button", {
      class: "btn btn--sm", text: "Rename", disabled: profile.read_only ? "disabled" : null,
      onclick: async () => {
        const name = await promptText({ title: "Rename Profile", label: "Profile name", initial: profile.name });
        if (!name) return;
        try {
          await api.post(`/api/golden/profiles/${activeId}/rename`, { name });
          profiles = await api.get("/api/golden/profiles");
          toastSuccess("Profile renamed.");
          await loadProfile(activeId);
        } catch (err) {
          toastError(err.detail);
        }
      },
    });

    const deleteBtn = el("button", {
      class: "btn btn--sm btn--danger", text: "Delete", disabled: profile.read_only ? "disabled" : null,
      onclick: async () => {
        const ok = await confirmDialog({
          title: "Delete this profile?", body: `Permanently delete "${profile.name}"? This cannot be undone.`,
          confirmLabel: "Delete", danger: true,
        });
        if (!ok) return;
        try {
          await api.del(`/api/golden/profiles/${activeId}`);
          profiles = await api.get("/api/golden/profiles");
          toastSuccess("Profile deleted.");
          const fallback = profiles.find((p) => !p.read_only) || profiles[0];
          await loadProfile(fallback.profile_id);
        } catch (err) {
          toastError(err.detail);
        }
      },
    });

    const restoreBtn = el("button", {
      class: "btn btn--sm", text: "Restore Default", disabled: profile.read_only ? "disabled" : null,
      onclick: async () => {
        const ok = await confirmDialog({
          title: "Restore Default Golden Config?",
          body: `This replaces all values in "${profile.name}" with the system Default. Your current edits will be lost.`,
          confirmLabel: "Restore Default", danger: true,
        });
        if (!ok) return;
        try {
          await api.post(`/api/golden/profiles/${activeId}/restore-default`);
          toastSuccess("Restored to Default.");
          await loadProfile(activeId);
        } catch (err) {
          toastError(err.detail);
        }
      },
    });

    const compareBtn = el("button", {
      class: "btn btn--sm", text: "Compare with Default",
      onclick: async () => {
        try {
          const { diff } = await api.get(`/api/golden/profiles/${activeId}/compare-default`);
          showDiffModal(profile.name, diff);
        } catch (err) {
          toastError(err.detail);
        }
      },
    });

    const importBtn = el("button", { class: "btn btn--sm", text: "Import .txt", onclick: () => showImportModal() });

    toolbar.appendChild(
      el("div", { class: "cluster", style: "justify-content: space-between;" }, [
        el("div", { class: "field", style: "margin-bottom: 0; min-width: 280px;" }, [
          el("label", { class: "field__label", text: "Active Golden Config" }),
          select,
        ]),
        dirtyBadge,
      ])
    );
    toolbar.appendChild(
      el("div", { class: "cluster", style: "margin-top: var(--space-3);" }, [
        newBtn, saveBtn, saveAsBtn, duplicateBtn, renameBtn, deleteBtn, restoreBtn, compareBtn, importBtn,
      ])
    );
    refreshDirtyUI();
  }

  async function loadProfile(id) {
    try {
      profile = await api.get(`/api/golden/profiles/${id}`);
    } catch (err) {
      toastError(err.detail);
      return;
    }
    activeId = id;
    setState({ activeGoldenProfileId: id });
    formVars = JSON.parse(JSON.stringify(profile.device_vars || {}));
    initialVarsJSON = JSON.stringify(formVars);
    buildToolbar();
    buildForm();
    updatePreview(profile.rendered_text, profile.missing, [], true);
  }

  await loadProfile(activeId);

  return () => clearTimeout(previewTimer);
}
