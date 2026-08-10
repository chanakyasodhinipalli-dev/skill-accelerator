/* DOM helpers.
 *
 * `el` builds elements from data, which keeps every view free of string
 * templates. That is not a style preference: a console renders user-supplied
 * text — form values, transcripts, email bodies — and building nodes with
 * textContent makes injection structurally impossible rather than a review
 * item on every innerHTML call.
 */

/**
 * el("div", {class: "card"}, "text", el("b", {}, "bold"))
 * Props: `class`, `text`, `html` (never for untrusted input), `on*` handlers,
 * `dataset`, anything else becomes an attribute or a property.
 */
export function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props ?? {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "html") node.innerHTML = value;
    else if (key === "dataset") Object.assign(node.dataset, value);
    else if (key.startsWith("on") && typeof value === "function") {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (key in node && typeof value !== "string") node[key] = value;
    else node.setAttribute(key, value === true ? "" : value);
  }
  node.append(...children.flat().filter((c) => c !== null && c !== undefined && c !== false));
  return node;
}

export function clear(node) {
  node.replaceChildren();
  return node;
}

export function badge(text, tone = "") {
  return el("span", { class: `badge ${tone}`.trim(), text: String(text) });
}

export function bar(percent, { done = false } = {}) {
  const value = Math.max(0, Math.min(100, Number(percent) || 0));
  return el(
    "div",
    {
      class: `bar${done ? " done" : ""}`,
      role: "progressbar",
      "aria-valuenow": String(Math.round(value)),
      "aria-valuemin": "0",
      "aria-valuemax": "100",
    },
    el("i", { style: `width:${value}%` }),
  );
}

export function field(label, control, hint) {
  return el("label", { class: "field" }, el("span", { text: label }), control, hint ? el("div", { class: "hint", text: hint }) : null);
}

export function card(title, ...children) {
  return el("section", { class: "card" }, title ? el("h2", { text: title }) : null, ...children);
}

export function empty(message) {
  return el("div", { class: "empty", text: message });
}

/** A table from column definitions and rows. Cells may be nodes or text. */
export function table(columns, rows, { emptyMessage = "Nothing here yet." } = {}) {
  if (!rows.length) return empty(emptyMessage);
  return el(
    "div",
    { class: "table-wrap" },
    el(
      "table",
      {},
      el("thead", {}, el("tr", {}, ...columns.map((c) => el("th", { text: c.label })))),
      el(
        "tbody",
        {},
        ...rows.map((row) =>
          el(
            "tr",
            {},
            ...columns.map((column) => {
              const value = column.render(row);
              return el("td", {}, value instanceof Node ? value : el("span", { text: value ?? "—" }));
            }),
          ),
        ),
      ),
    ),
  );
}

export function tabs(items, { onSelect, selected } = {}) {
  const bar = el("div", { class: "tabs", role: "tablist" });
  items.forEach((item) => {
    bar.append(
      el("button", {
        type: "button",
        role: "tab",
        text: item.label,
        "aria-selected": String(item.id === selected),
        onClick: () => onSelect(item.id),
      }),
    );
  });
  return bar;
}

let toastTimer = 0;

export function toast(title, { detail = "", tone = "" } = {}) {
  const host = document.getElementById("toasts");
  const node = el(
    "div",
    { class: `toast ${tone}`.trim() },
    el("div", { class: "toast-title", text: title }),
    detail ? el("div", { class: "toast-detail", text: detail }) : null,
  );
  host.append(node);
  // Errors stay long enough to read a correlation id off them.
  const life = tone === "error" ? 9000 : 4200;
  toastTimer = window.setTimeout(() => node.remove(), life);
  return () => {
    window.clearTimeout(toastTimer);
    node.remove();
  };
}

/** Report a failure without losing the diagnostic detail. */
export function reportError(error, context = "") {
  const parts = [];
  if (error?.code && error.code !== "http_error") parts.push(error.code);
  if (error?.correlationId) parts.push(`correlation ${error.correlationId}`);
  for (const message of error?.fieldErrors ?? []) parts.push(message);
  toast(context || "Request failed", {
    detail: `${error?.message ?? error}${parts.length ? ` — ${parts.join(" · ")}` : ""}`,
    tone: "error",
  });
  return error;
}

export function modal(title, body, actions = []) {
  const dialog = document.getElementById("modal");
  clear(dialog);
  dialog.append(
    el(
      "form",
      { method: "dialog", class: "modal-body" },
      el("h2", { text: title }),
      body,
      el(
        "div",
        { class: "row", style: "justify-content:flex-end;margin-top:16px" },
        el("button", { type: "submit", value: "cancel", text: "Close" }),
        ...actions.map((action) =>
          el("button", {
            type: "button",
            class: action.class ?? "primary",
            text: action.label,
            onClick: async () => {
              await action.run();
              dialog.close();
            },
          }),
        ),
      ),
    ),
  );
  dialog.showModal();
  return dialog;
}

/** Run an async action with a busy state, so double-clicks cannot double-submit. */
export async function withBusy(node, work) {
  node?.classList.add("busy");
  try {
    return await work();
  } finally {
    node?.classList.remove("busy");
  }
}

export function timeAgo(epochSeconds) {
  if (!epochSeconds) return "—";
  const seconds = Math.max(0, Date.now() / 1000 - epochSeconds);
  const steps = [
    [60, "s"],
    [3600, "m", 60],
    [86400, "h", 3600],
    [2592000, "d", 86400],
  ];
  if (seconds < 60) return `${Math.round(seconds)}s ago`;
  for (const [limit, unit, divisor] of steps.slice(1)) {
    if (seconds < limit) return `${Math.round(seconds / divisor)}${unit} ago`;
  }
  return new Date(epochSeconds * 1000).toLocaleDateString();
}

export function stringify(value) {
  return typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

/** Present a value for reading: arrays as lists, objects as JSON, null as a dash. */
export function displayValue(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
