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

// A deliberately minimal, safe Markdown-to-DOM renderer for LLM/report-authored
// prose (briefings, compliance report markdown) - headings/bullets/paragraphs
// only, everything via textContent (never innerHTML), so untrusted text can
// never become markup. Not a general Markdown parser by design.
export function renderMarkdownLite(container, text) {
  clear(container);
  let listEl = null;
  for (const rawLine of (text || "").split("\n")) {
    const line = rawLine.trimEnd();
    const headingMatch = /^(#{1,4})\s+(.*)$/.exec(line);
    const bulletMatch = /^[-*]\s+(.*)$/.exec(line);
    if (headingMatch) {
      listEl = null;
      const level = Math.min(headingMatch[1].length + 1, 6);
      container.appendChild(el(`h${level}`, { text: headingMatch[2] }));
    } else if (bulletMatch) {
      if (!listEl) {
        listEl = el("ul", {});
        container.appendChild(listEl);
      }
      listEl.appendChild(el("li", { text: bulletMatch[1] }));
    } else if (line.trim() === "") {
      listEl = null;
    } else {
      listEl = null;
      container.appendChild(el("p", { text: line }));
    }
  }
}
