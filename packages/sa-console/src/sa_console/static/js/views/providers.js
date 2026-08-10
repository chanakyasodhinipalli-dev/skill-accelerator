/* Models: which provider answers, prove it works, add another, compare them.
 *
 * The switching story only means something if you can see it happen, so this
 * page shows the routing decision, per-profile counters, and side-by-side
 * output from several vendors on the same prompt.
 */

import { api } from "../api.js";
import { badge, card, el, field, reportError, table, toast, withBusy } from "../ui.js";
import { refreshProfiles } from "../profiles.js";
import { state } from "../state.js";

const VENDORS = [
  { id: "anthropic", label: "Anthropic (SDK)" },
  { id: "openai", label: "OpenAI / OpenAI-compatible" },
  { id: "gemini", label: "Google Gemini" },
  { id: "gateway", label: "Enterprise gateway" },
  { id: "stub", label: "Deterministic (no model)" },
];

export async function render(root, _params) {
  root.append(
    el(
      "div",
      { class: "page-head" },
      el("h1", { text: "Models" }),
      el("p", {
        class: "lede",
        text: "Every component asks the router for a provider, so switching vendors is configuration rather than code. A profile can reach a vendor directly or go through a gateway that fronts several of them.",
      }),
    ),
  );

  const body = el("div", {});
  root.append(body);
  await load(body);
}

async function load(body) {
  const [data, health] = await Promise.all([
    api.get("/providers"),
    api.get("/providers/health").catch(() => ({})),
  ]);

  body.replaceChildren(
    card(
      "Profiles",
      el("p", {
        class: "hint",
        text: "Activating changes the server default for everyone. The picker in the header only pins requests from this console, using the X-LLM-Profile header.",
      }),
      table(
        [
          {
            label: "Profile",
            render: (p) =>
              el(
                "div",
                {},
                el("strong", { text: p.label }),
                el("div", { class: "mono muted", text: p.name }),
              ),
          },
          {
            label: "Vendor",
            render: (p) =>
              el(
                "div",
                { class: "row tight" },
                badge(p.vendor, p.active ? "accent" : ""),
                p.via_gateway ? badge(`via gateway → ${p.wire}`, "warn") : null,
              ),
          },
          { label: "Model", render: (p) => el("code", { text: p.model }) },
          {
            label: "Endpoint",
            render: (p) => el("span", { class: "mono muted", text: p.base_url || "vendor default" }),
          },
          {
            label: "Credential",
            render: (p) =>
              p.credential_present ? badge("present", "ok") : badge("missing", "bad"),
          },
          {
            label: "Reachable",
            render: (p) => {
              const result = health[p.name];
              if (!result) return badge("unknown");
              return badge(result.status, result.status === "healthy" ? "ok" : "bad");
            },
          },
          {
            label: "Traffic",
            render: (p) =>
              el("span", {
                class: "muted",
                text: `${p.stats.calls} calls · ${p.stats.failures} failed · ${p.stats.average_latency_ms}ms avg · ${p.stats.output_tokens} out`,
              }),
          },
          {
            label: "",
            render: (p) =>
              el(
                "div",
                { class: "row tight" },
                el("button", {
                  text: "Test",
                  onClick: (event) => test(p.name, event.target),
                }),
                el("button", {
                  text: "Models",
                  title: "Ask the endpoint what it will serve",
                  onClick: () => listModels(p.name),
                }),
                el("button", {
                  class: p.active ? "" : "primary",
                  text: p.active ? "Active" : "Activate",
                  disabled: p.active,
                  onClick: async () => {
                    try {
                      await api.post(`/providers/${p.name}/activate`);
                      toast(`${p.name} is now the server default`, { tone: "success" });
                      await Promise.all([load(body), refreshProfiles()]);
                    } catch (error) {
                      reportError(error, "Could not switch the active profile");
                    }
                  },
                }),
              ),
          },
        ],
        data.profiles,
      ),
    ),
  );

  body.append(registerCard(body));
  body.append(compareCard(data.profiles));
}

async function test(name, button) {
  try {
    const result = await withBusy(button, () => api.post(`/providers/${name}/test`));
    if (result.ok) {
      toast(`${name} answered in ${result.latency_ms}ms`, {
        detail: `${result.model}: ${result.text.slice(0, 120) || "(empty reply)"}`,
        tone: "success",
      });
    } else {
      toast(`${name} failed`, { detail: `${result.error_type}: ${result.error}`, tone: "error" });
    }
  } catch (error) {
    reportError(error, "The probe could not run");
  }
}

async function listModels(name) {
  try {
    const data = await api.get(`/providers/${name}/models`);
    toast(`${data.models.length} model(s) available on ${name}`, {
      detail: data.models.slice(0, 12).join(", "),
    });
  } catch (error) {
    reportError(error, "Could not list models");
  }
}

function registerCard(body) {
  const name = el("input", { type: "text", placeholder: "e.g. openai-prod" });
  const vendor = el(
    "select",
    {},
    ...VENDORS.map((v) => el("option", { value: v.id, text: v.label })),
  );
  const model = el("input", { type: "text", placeholder: "e.g. gpt-4o, gemini-2.0-flash" });
  const baseUrl = el("input", { type: "text", placeholder: "https://gateway.internal/v1" });
  const apiKey = el("input", { type: "password", placeholder: "leave blank to use the environment" });
  const apiKeyEnv = el("input", { type: "text", placeholder: "e.g. OPENAI_API_KEY" });
  const dialect = el(
    "select",
    {},
    el("option", { value: "openai", text: "openai — the common gateway shape" }),
    el("option", { value: "anthropic", text: "anthropic — Messages API" }),
    el("option", { value: "gemini", text: "gemini — generateContent" }),
  );
  const authHeader = el("input", { type: "text", placeholder: "e.g. api-key, x-virtual-key" });
  const headers = el("textarea", { class: "code", placeholder: '{"x-tenant-id": "risk-platform"}' });
  const activate = el("input", { type: "checkbox" });

  const gatewayFields = el(
    "div",
    { hidden: true },
    field("Dialect", dialect, "What this side of the call looks like. The gateway may route to any vendor behind it."),
    field("Auth header", authHeader, "Blank uses the vendor default (Authorization: Bearer, or x-api-key)."),
    field("Extra headers", headers, "JSON. Tenant ids, cost centres, routing hints, virtual keys."),
  );
  vendor.addEventListener("change", () => {
    gatewayFields.hidden = vendor.value !== "gateway";
  });

  return card(
    "Add a profile",
    el("p", {
      class: "hint",
      text: "Registered in process memory only — a credential typed here is never written to disk and never returned by any endpoint. Put it in the environment or a config file to survive a restart.",
    }),
    field("Name", name),
    field("Vendor", vendor),
    field("Model", model),
    field("Endpoint", baseUrl, "Required for a gateway. Also how Azure OpenAI, vLLM, or a proxy is reached."),
    field("API key", apiKey, "Optional — leave blank and the vendor's usual environment variable is used."),
    field("…or the variable holding it", apiKeyEnv),
    gatewayFields,
    el("label", { class: "row tight" }, activate, el("span", { text: "Make it the server default" })),
    el("button", {
      class: "primary",
      style: "margin-top:10px",
      text: "Register",
      onClick: async (event) => {
        let extraHeaders = {};
        if (headers.value.trim()) {
          try {
            extraHeaders = JSON.parse(headers.value);
          } catch {
            toast("Extra headers must be JSON", { tone: "error" });
            return;
          }
        }
        try {
          await withBusy(event.target, () =>
            api.post("/providers", {
              name: name.value.trim(),
              vendor: vendor.value,
              model: model.value.trim(),
              base_url: baseUrl.value.trim() || undefined,
              api_key: apiKey.value || undefined,
              api_key_env: apiKeyEnv.value.trim() || undefined,
              dialect: vendor.value === "gateway" ? dialect.value : undefined,
              auth_header: vendor.value === "gateway" ? authHeader.value.trim() : "",
              headers: extraHeaders,
              activate: activate.checked,
            }),
          );
          toast(`Profile ${name.value} registered`, { tone: "success" });
          apiKey.value = "";
          await Promise.all([load(body), refreshProfiles()]);
        } catch (error) {
          reportError(error, "The profile was rejected");
        }
      },
    }),
  );
}

function compareCard(profiles) {
  const prompt = el("textarea", {
    placeholder: "One prompt, several vendors. Useful for choosing a model — and for checking a gateway routes where it claims to.",
  });
  const results = el("div", {});
  const chosen = new Set(profiles.filter((p) => p.credential_present).slice(0, 2).map((p) => p.name));

  const boxes = profiles.map((profile) => {
    const box = el("input", { type: "checkbox", checked: chosen.has(profile.name) });
    box.addEventListener("change", () =>
      box.checked ? chosen.add(profile.name) : chosen.delete(profile.name),
    );
    return el("label", { class: "row tight" }, box, el("span", { text: profile.name }));
  });

  return card(
    "Compare",
    el("div", { class: "row" }, ...boxes),
    prompt,
    el("button", {
      class: "primary",
      style: "margin-top:10px",
      text: "Run on each",
      onClick: async (event) => {
        if (!prompt.value.trim() || !chosen.size) {
          toast("Pick at least one profile and write a prompt");
          return;
        }
        try {
          const data = await withBusy(event.target, () =>
            api.post("/providers/compare", { prompt: prompt.value, profiles: [...chosen] }),
          );
          results.replaceChildren(
            ...data.results.map((result) =>
              el(
                "div",
                { style: "margin-top:12px" },
                el(
                  "div",
                  { class: "row tight" },
                  badge(result.profile, result.ok ? "ok" : "bad"),
                  result.ok
                    ? el("span", {
                        class: "muted",
                        text: `${result.model} · ${result.latency_ms}ms · ${result.usage.output_tokens} output tokens`,
                      })
                    : null,
                ),
                el("pre", { class: "output", text: result.ok ? result.text : result.error }),
              ),
            ),
          );
        } catch (error) {
          reportError(error, "Comparison failed");
        }
      },
    }),
    results,
    state.profileOverride
      ? el("p", {
          class: "hint",
          text: `This console is currently pinned to "${state.profileOverride}" for every other request.`,
        })
      : null,
  );
}
