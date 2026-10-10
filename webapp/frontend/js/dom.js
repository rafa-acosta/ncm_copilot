// Tiny DOM helpers used everywhere instead of innerHTML-with-interpolation,
// so untrusted content (uploaded filenames, config text, LLM-authored
// briefing prose) can never be accidentally rendered as HTML - see
// webapp/README.md's security notes.

export function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value; // always-safe text content
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
    else if (value !== null && value !== undefined && value !== false) node.setAttribute(key, value);
  }
  for (const child of [].concat(children)) {
    if (child === null || child === undefined || child === false) continue;
    node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
  }
  return node;
}

export function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

export function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatTimestamp(value) {
  if (!value) return "—";
  const date = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return date.toLocaleString(undefined, {
    year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

export function formatPct(value) {
  if (value === null || value === undefined) return "—";
  return `${value}%`;
}

// One duration formatter used everywhere a run/stage timing needs to be
// shown (Overview, Analysis, Briefings, Dashboard, Compliance Report, and
// the live elapsed-time indicator in jobProgress.js) - see runStatus.js for
// the status-badge counterpart. `seconds` may be null/undefined (a legacy
// run with no recorded timing, or a stage that hasn't run) - renders "N/A",
// never a misleading "0s" or a thrown error.
export function formatDuration(seconds) {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "N/A";
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) return `${seconds < 10 ? seconds.toFixed(1) : total}s`;
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h}h ${String(m).padStart(2, "0")}m ${String(s).padStart(2, "0")}s`;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

// Inline Markdown spans (code/bold/italic) applied to one line's worth of
// text - appends a mix of text nodes and <code>/<strong>/<em> elements,
// always via el()'s textContent path, never innerHTML, so untrusted
// LLM/report-authored text can never become markup (see renderMarkdownLite).
// No bare `_..._` italic pattern: this app's content is full of snake_case
// identifiers (device names, control IDs, filenames, model names like
// "phi4_mini") - CommonMark itself disables underscore emphasis mid-word for
// exactly this reason, so single-underscore spans are deliberately left as
// plain text rather than mis-parsed as emphasis (verified against a real
// briefing - "ncm_test_0201_anom_14" was rendering as "ncmtest0201anom14"
// with "test"/"anom" italicized before this was excluded).
const _INLINE_RE = /(`[^`]+`)|(\*\*[^*]+\*\*)|(__[^_]+__)|(\*[^*\s][^*]*\*)/;

function appendInline(parent, text) {
  let remaining = text;
  while (remaining) {
    const match = _INLINE_RE.exec(remaining);
    if (!match) {
      parent.appendChild(document.createTextNode(remaining));
      return;
    }
    if (match.index > 0) parent.appendChild(document.createTextNode(remaining.slice(0, match.index)));
    const token = match[0];
    if (token.startsWith("`")) {
      parent.appendChild(el("code", { text: token.slice(1, -1) }));
    } else if (token.startsWith("**") || token.startsWith("__")) {
      parent.appendChild(el("strong", { text: token.slice(2, -2) }));
    } else {
      parent.appendChild(el("em", { text: token.slice(1, -1) }));
    }
    remaining = remaining.slice(match.index + token.length);
  }
}

const _TABLE_SEPARATOR_RE = /^\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?$/;

function splitTableRow(line) {
  return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
}

// A safe Markdown-to-DOM renderer for LLM/report-authored prose (briefings,
// compliance report markdown): headings, paragraphs, bulleted/numbered lists,
// blockquotes, fenced code blocks, horizontal rules, GFM tables, and inline
// bold/italic/code - everything built as real DOM nodes via el()'s
// always-safe textContent path, never innerHTML, so untrusted text can never
// become markup. Not a spec-complete Markdown parser (no nested lists, no
// reference-style links) - just what this app's own generated content uses.
export function renderMarkdownLite(container, text) {
  clear(container);
  const lines = (text || "").split("\n");
  let i = 0;
  let listEl = null;
  let quoteEl = null;

  while (i < lines.length) {
    const line = lines[i].trimEnd();
    const trimmed = line.trim();

    if (trimmed === "") {
      listEl = null;
      quoteEl = null;
      i++;
      continue;
    }

    const fenceMatch = /^```(.*)$/.exec(trimmed);
    if (fenceMatch) {
      listEl = null;
      quoteEl = null;
      const codeLines = [];
      i++;
      while (i < lines.length && lines[i].trim() !== "```") {
        codeLines.push(lines[i]);
        i++;
      }
      i++; // skip closing fence (or end of text, if unterminated)
      const pre = el("pre", {}, [el("code", { text: codeLines.join("\n") })]);
      container.appendChild(pre);
      continue;
    }

    if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
      listEl = null;
      quoteEl = null;
      container.appendChild(el("hr", {}));
      i++;
      continue;
    }

    if (/^\|.*\|$/.test(trimmed) && i + 1 < lines.length && _TABLE_SEPARATOR_RE.test(lines[i + 1].trim())) {
      listEl = null;
      quoteEl = null;
      const headerCells = splitTableRow(trimmed);
      i += 2;
      const bodyRows = [];
      while (i < lines.length && /^\|.*\|$/.test(lines[i].trim())) {
        bodyRows.push(splitTableRow(lines[i]));
        i++;
      }
      const thead = el("thead", {}, [
        el(
          "tr", {},
          headerCells.map((c) => {
            const th = el("th", {});
            appendInline(th, c);
            return th;
          })
        ),
      ]);
      const tbody = el(
        "tbody", {},
        bodyRows.map((row) =>
          el(
            "tr", {},
            row.map((c) => {
              const td = el("td", {});
              appendInline(td, c);
              return td;
            })
          )
        )
      );
      container.appendChild(el("div", { class: "data-table-wrap" }, [el("table", { class: "data-table" }, [thead, tbody])]));
      continue;
    }

    const headingMatch = /^(#{1,6})\s+(.*)$/.exec(line);
    if (headingMatch) {
      listEl = null;
      quoteEl = null;
      const level = Math.min(headingMatch[1].length + 1, 6);
      const h = el(`h${level}`, {});
      appendInline(h, headingMatch[2]);
      container.appendChild(h);
      i++;
      continue;
    }

    const quoteMatch = /^>\s?(.*)$/.exec(line);
    if (quoteMatch) {
      listEl = null;
      if (!quoteEl) {
        quoteEl = el("blockquote", {});
        container.appendChild(quoteEl);
      }
      const p = el("p", {});
      appendInline(p, quoteMatch[1]);
      quoteEl.appendChild(p);
      i++;
      continue;
    }
    quoteEl = null;

    const orderedMatch = /^\d+\.\s+(.*)$/.exec(line);
    if (orderedMatch) {
      if (!listEl || listEl.tagName !== "OL") {
        listEl = el("ol", {});
        container.appendChild(listEl);
      }
      const li = el("li", {});
      appendInline(li, orderedMatch[1]);
      listEl.appendChild(li);
      i++;
      continue;
    }

    const bulletMatch = /^[-*]\s+(.*)$/.exec(line);
    if (bulletMatch) {
      if (!listEl || listEl.tagName !== "UL") {
        listEl = el("ul", {});
        container.appendChild(listEl);
      }
      const li = el("li", {});
      appendInline(li, bulletMatch[1]);
      listEl.appendChild(li);
      i++;
      continue;
    }
    listEl = null;

    const p = el("p", {});
    appendInline(p, line);
    container.appendChild(p);
    i++;
  }
}
