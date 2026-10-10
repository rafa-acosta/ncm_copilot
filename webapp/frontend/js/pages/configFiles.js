import { api } from "../api.js";
import { el, clear, formatBytes, formatTimestamp } from "../dom.js";
import { errorPanel } from "../components/errorPanel.js";
import { toastSuccess, toastError, toastWarning } from "../components/toast.js";
import { confirmDialog } from "../components/modal.js";

let selected = new Set();

export async function render(container) {
  clear(container);
  selected = new Set();

  container.appendChild(
    el("div", { class: "page-header" }, [
      el("div", { class: "page-header__heading" }, [
        el("h1", { text: "Configuration Files" }),
        el("p", { text: "Upload device running-configs to audit. Only .txt files are accepted." }),
      ]),
      el("div", { class: "page-header__actions" }, [
        el("input", {
          type: "file", id: "file-input", multiple: "multiple", accept: ".txt", class: "visually-hidden",
          onchange: (e) => handleUpload(e.target.files),
        }),
        el("input", {
          type: "file", id: "folder-input", webkitdirectory: "true", directory: "true", multiple: "multiple",
          class: "visually-hidden", onchange: (e) => handleUpload(e.target.files),
        }),
        el("button", { class: "btn", text: "Upload Folder", onclick: () => document.getElementById("folder-input").click() }),
        el("button", { class: "btn btn--primary", text: "Upload Files", onclick: () => document.getElementById("file-input").click() }),
      ]),
    ])
  );

  const body = el("div", {});
  container.appendChild(body);
  await renderTable(body);
}

async function handleUpload(fileList) {
  const files = Array.from(fileList).filter((f) => !f.webkitRelativePath || !f.webkitRelativePath.endsWith("/"));
  if (!files.length) return;
  let result;
  try {
    result = await api.upload("/api/configs/upload", files);
  } catch (err) {
    toastError(err.detail);
    return;
  }
  if (result.accepted_count) toastSuccess(`${result.accepted_count} file(s) uploaded.`);
  if (result.rejected_count) {
    const rejected = result.outcomes.filter((o) => o.status === "rejected");
    toastWarning(`${result.rejected_count} file(s) rejected: ${rejected.map((o) => `${o.filename} (${o.reason})`).join("; ")}`, {
      timeout: 9000,
    });
  }
  const body = document.querySelector("#main-content > div:last-child");
  if (body) await renderTable(body);
}

async function renderTable(body) {
  clear(body);
  body.appendChild(el("div", { class: "skeleton skeleton--block" }));

  let files;
  try {
    files = await api.get("/api/configs");
  } catch (err) {
    clear(body);
    body.appendChild(errorPanel(err, { title: "Unable to load configuration files" }));
    return;
  }
  clear(body);

  if (!files.length) {
    body.appendChild(
      el("div", { class: "empty-state card" }, [
        el("div", { class: "empty-state__icon", text: "\u{1F4C1}" }),
        el("div", { class: "empty-state__title", text: "No configuration files yet" }),
        el("p", { text: "Upload one or more Cisco device running-configs to get started." }),
      ])
    );
    return;
  }

  // Stale-selection guard: a file selected in a previous render of this table
  // (or carried over from before an upload/delete refreshed `files`) must
  // never stay "selected" once it no longer exists - otherwise counters and
  // bulk actions would silently operate on filenames that are gone.
  const validFilenames = new Set(files.map((f) => f.filename));
  for (const filename of Array.from(selected)) {
    if (!validFilenames.has(filename)) selected.delete(filename);
  }

  let search = "";
  const counters = el("div", { class: "cluster", style: "gap: var(--space-4); margin-bottom: var(--space-2);" });
  body.appendChild(counters);

  const toolbar = el("div", { class: "table-toolbar" }, [
    el("input", {
      class: "input", style: "max-width: 280px;", placeholder: "Search filename or device...",
      oninput: (e) => {
        search = e.target.value.toLowerCase();
        renderRows();
      },
    }),
    el("div", { class: "cluster" }, [
      el("button", {
        class: "btn btn--sm", text: "Delete Selected",
        onclick: () => deleteSelected(Array.from(selected), body),
      }),
      el("button", {
        class: "btn btn--sm btn--danger", text: "Delete All",
        onclick: () => deleteAll(body),
      }),
    ]),
  ]);
  body.appendChild(toolbar);

  const tableWrap = el("div", { class: "data-table-wrap" });
  body.appendChild(tableWrap);

  function updateCounters() {
    clear(counters);
    counters.appendChild(counterStat(String(files.length), "files loaded"));
    counters.appendChild(counterStat(String(selected.size), "files selected"));
    // Every uploaded config is a plain, already-validated .txt file (see
    // configs_service.save_uploads) - there is no separate "invalid config"
    // concept in this app, so everything selected is what Analysis will
    // actually process. See analysis.js for where this number is consumed.
    counters.appendChild(counterStat(String(selected.size), "ready for analysis"));
  }

  function renderRows() {
    clear(tableWrap);
    const visible = files.filter(
      (f) => f.filename.toLowerCase().includes(search) || (f.device_name || "").toLowerCase().includes(search)
    );
    const visibleSelectedCount = visible.filter((f) => selected.has(f.filename)).length;
    const allVisibleSelected = visible.length > 0 && visibleSelectedCount === visible.length;
    const selectAllCheckbox = el("input", {
      type: "checkbox",
      "aria-label": "Select all",
      onchange: (e) => {
        if (e.target.checked) visible.forEach((f) => selected.add(f.filename));
        else visible.forEach((f) => selected.delete(f.filename));
        renderRows();
      },
    });
    selectAllCheckbox.checked = allVisibleSelected;
    selectAllCheckbox.indeterminate = !allVisibleSelected && visibleSelectedCount > 0;

    const table = el("table", { class: "data-table" }, [
      el("thead", {}, [
        el("tr", {}, [
          el("th", {}, [selectAllCheckbox]),
          el("th", { text: "Filename" }),
          el("th", { text: "Detected Device" }),
          el("th", { text: "Size" }),
          el("th", { text: "Uploaded" }),
          el("th", { text: "" }),
        ]),
      ]),
      el(
        "tbody",
        {},
        visible.map((f) =>
          el("tr", {}, [
            el("td", {}, [
              el("input", {
                type: "checkbox",
                checked: selected.has(f.filename) ? "checked" : null,
                "aria-label": `Select ${f.filename}`,
                onchange: (e) => {
                  if (e.target.checked) selected.add(f.filename);
                  else selected.delete(f.filename);
                  updateCounters();
                  // Only the header checkbox's checked/indeterminate state
                  // needs to stay in sync with individual toggles - not
                  // worth a full renderRows() (and losing focus) per click.
                  const visibleNowSelected = visible.filter((v) => selected.has(v.filename)).length;
                  selectAllCheckbox.checked = visible.length > 0 && visibleNowSelected === visible.length;
                  selectAllCheckbox.indeterminate = selectAllCheckbox.checked ? false : visibleNowSelected > 0;
                },
              }),
            ]),
            el("td", { text: f.filename }),
            el("td", { text: f.device_name || "—" }),
            el("td", { text: formatBytes(f.size_bytes) }),
            el("td", { text: formatTimestamp(f.modified_at) }),
            el("td", {}, [
              el("button", {
                class: "btn-icon", "aria-label": `Delete ${f.filename}`, title: "Delete",
                onclick: () => deleteSelected([f.filename], body),
                text: "✕",
              }),
            ]),
          ])
        )
      ),
    ]);
    tableWrap.appendChild(table);
    updateCounters();
  }
  renderRows();
}

function counterStat(value, label) {
  return el("div", { class: "cluster", style: "gap: 4px;" }, [
    el("strong", { text: value }),
    el("span", { class: "muted", text: label }),
  ]);
}

async function deleteSelected(filenames, body) {
  if (!filenames.length) {
    toastWarning("No files selected.");
    return;
  }
  const ok = await confirmDialog({
    title: "Delete configuration file(s)?",
    body: `Delete ${filenames.length} selected configuration file(s)? This cannot be undone.`,
    confirmLabel: "Delete",
    danger: true,
  });
  if (!ok) return;
  try {
    await api.post("/api/configs/delete", { filenames });
    toastSuccess(`${filenames.length} file(s) deleted.`);
  } catch (err) {
    toastError(err.detail);
  }
  await renderTable(body);
}

async function deleteAll(body) {
  const files = await api.get("/api/configs");
  if (!files.length) return;
  const ok = await confirmDialog({
    title: "Delete all configuration files?",
    body: `This permanently deletes all ${files.length} uploaded configuration files.`,
    confirmLabel: "Delete All",
    danger: true,
    requireTypedValue: "DELETE ALL",
  });
  if (!ok) return;
  try {
    await api.post("/api/configs/delete", { all: true });
    toastSuccess("All configuration files deleted.");
  } catch (err) {
    toastError(err.detail);
  }
  await renderTable(body);
}
