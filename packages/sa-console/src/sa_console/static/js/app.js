/* Console shell: configuration, theme, identity, model selection, routing. */

import { api, setHeader, ApiError } from "./api.js";
import { clear, el, reportError, toast } from "./ui.js";
import { state } from "./state.js";
import { refreshProfiles } from "./profiles.js";

import * as overview from "./views/overview.js";
import * as forms from "./views/forms.js";
import * as builder from "./views/builder.js";
import * as sessions from "./views/sessions.js";
import * as session from "./views/session.js";
import * as artifacts from "./views/artifacts.js";
import * as assistant from "./views/assistant.js";
import * as providers from "./views/providers.js";
import * as platform from "./views/platform.js";

const NAV = [
  { id: "overview", label: "Overview", glyph: "◎", route: "#/overview" },
  { id: "forms", label: "Forms", glyph: "▤", route: "#/forms" },
  { id: "builder", label: "Form builder", glyph: "✦", route: "#/builder" },
  { id: "sessions", label: "Sessions", glyph: "✎", route: "#/sessions" },
  { id: "artifacts", label: "Artifacts", glyph: "◈", route: "#/artifacts" },
  { id: "assistant", label: "Assistant", glyph: "✱", route: "#/assistant" },
  { id: "providers", label: "Models", glyph: "⌁", route: "#/providers" },
  { id: "platform", label: "Platform", glyph: "⚙", route: "#/platform" },
];

const ROUTES = [
  { pattern: /^#\/overview$/, view: overview, nav: "overview" },
  { pattern: /^#\/forms$/, view: forms, nav: "forms" },
  { pattern: /^#\/forms\/([^/]+)$/, view: forms, nav: "forms", params: ["name"] },
  { pattern: /^#\/builder$/, view: builder, nav: "builder" },
  { pattern: /^#\/sessions$/, view: sessions, nav: "sessions" },
  { pattern: /^#\/session\/([^/]+)$/, view: session, nav: "sessions", params: ["id"] },
  { pattern: /^#\/artifacts$/, view: artifacts, nav: "artifacts" },
  { pattern: /^#\/assistant$/, view: assistant, nav: "assistant" },
  { pattern: /^#\/providers$/, view: providers, nav: "providers" },
  { pattern: /^#\/platform$/, view: platform, nav: "platform" },
];

function buildNav() {
  const list = document.getElementById("nav");
  clear(list);
  for (const item of NAV) {
    list.append(
      el(
        "li",
        {},
        el(
          "a",
          { href: item.route, dataset: { nav: item.id } },
          el("span", { class: "nav-glyph", text: item.glyph, "aria-hidden": "true" }),
          el("span", { text: item.label }),
        ),
      ),
    );
  }
}

function markNav(id) {
  for (const link of document.querySelectorAll("#nav a")) {
    if (link.dataset.nav === id) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
}

// -- theme ------------------------------------------------------------------

function applyTheme(theme) {
  const resolved =
    theme === "auto"
      ? window.matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light"
      : theme;
  document.documentElement.dataset.theme = resolved;
}

function setupTheme() {
  applyTheme(state.theme);
  document.getElementById("theme-toggle").addEventListener("click", () => {
    state.theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    applyTheme(state.theme);
  });
  window
    .matchMedia("(prefers-color-scheme: dark)")
    .addEventListener("change", () => state.theme === "auto" && applyTheme("auto"));
}

// -- identity and model selection -------------------------------------------

function setupIdentity(config) {
  const input = document.getElementById("participant");
  input.value = state.participant || config.default_participant || "operator";
  state.participant = input.value;
  input.addEventListener("change", () => {
    state.participant = input.value.trim() || "operator";
    toast(`Acting as ${state.participant}`);
    // Views key on identity ("my sessions", self-approval rules), so re-render.
    route();
  });
}

function setupProfilePicker() {
  document.getElementById("profile-picker").addEventListener("change", (event) => {
    state.profileOverride = event.target.value || null;
    setHeader("X-LLM-Profile", state.profileOverride);
    toast(
      state.profileOverride
        ? `Requests from this console now use "${state.profileOverride}"`
        : "Requests now use the server's active profile",
    );
  });
}

// -- routing ----------------------------------------------------------------

async function route() {
  const hash = window.location.hash || "#/overview";
  const container = document.getElementById("view");

  const match = ROUTES.map((r) => ({ r, m: hash.match(r.pattern) })).find((entry) => entry.m);
  if (!match) {
    window.location.hash = "#/overview";
    return;
  }

  const params = {};
  (match.r.params ?? []).forEach((name, index) => {
    params[name] = decodeURIComponent(match.m[index + 1]);
  });

  markNav(match.r.nav);
  clear(container);
  container.append(el("div", { class: "muted", text: "Loading…" }));

  try {
    clear(container);
    await match.r.view.render(container, params);
  } catch (error) {
    clear(container);
    container.append(
      el(
        "section",
        { class: "card" },
        el("h2", { text: "This view could not load" }),
        el("p", { class: "lede", text: error?.message ?? String(error) }),
        error instanceof ApiError && error.correlationId
          ? el("p", { class: "mono muted", text: `correlation ${error.correlationId}` })
          : null,
        el("button", { class: "primary", text: "Retry", onClick: route }),
      ),
    );
    reportError(error, "View failed to load");
  }
}

async function checkApi() {
  const dot = document.getElementById("api-status");
  try {
    // The readiness probe aggregates the registered checks; /health is only
    // service information and would report "up" on a broken deployment.
    const health = await api.get("/health/ready");
    const ok = health.status === "healthy" || health.status === "degraded";
    dot.classList.toggle("ok", ok);
    dot.classList.toggle("bad", !ok);
    dot.title = `Platform API: ${health.status}`;
  } catch {
    dot.classList.add("bad");
    dot.title = "Platform API unreachable";
  }
}

async function start() {
  buildNav();
  setupTheme();
  setupProfilePicker();

  // The console's own config is served by the console, not the platform API.
  const config = await fetch("/console/config")
    .then((response) => response.json())
    .catch(() => ({
      title: "Skill Accelerator",
      default_participant: "operator",
      mode: "embedded",
      theme: "auto",
    }));

  document.getElementById("app-title").textContent = config.title ?? "Skill Accelerator";
  document.title = config.title ?? "Skill Accelerator Console";
  if (config.environment_banner) {
    const banner = document.getElementById("env-banner");
    banner.textContent = config.environment_banner;
    banner.hidden = false;
  }
  document.getElementById("api-mode").textContent = config.mode === "remote" ? "remote" : "embedded";
  if (state.theme === "auto" && config.theme && config.theme !== "auto") {
    state.theme = config.theme;
    applyTheme(state.theme);
  }

  setupIdentity(config);
  await Promise.all([refreshProfiles(), checkApi()]);

  window.addEventListener("hashchange", route);
  await route();
  // A slow-moving indicator; polling it hard would add noise, not signal.
  window.setInterval(checkApi, 30000);
}

start();
