/* Platform: what is registered, and what the model is allowed to do with it.
 *
 * Read-mostly on purpose. Skills, tools, and workflows are deployed artefacts;
 * a console that let you edit them here would be editing a copy of the truth.
 * Invocation is included because "does this tool actually work" is a question
 * worth answering without writing a client.
 */

import { api } from "../api.js";
import { badge, card, el, field, modal, reportError, table, tabs, toast, withBusy } from "../ui.js";

const DANGER_TONE = { safe: "ok", low: "", medium: "warn", high: "bad", critical: "bad" };

export async function render(root, _params) {
  root.append(
    el(
      "div",
      { class: "page-head" },
      el("h1", { text: "Platform" }),
      el("p", {
        class: "lede",
        text: "Skills become tools automatically, and MCP and OpenAPI tools land in the same registry — so they pass through the same policy, approval, and audit path. There is no privileged side channel.",
      }),
    ),
  );

  const panel = el("div", {});
  const SECTIONS = [
    { id: "tools", label: "Tools" },
    { id: "skills", label: "Skills" },
    { id: "workflows", label: "Workflows" },
    { id: "connectors", label: "Connectors" },
  ];
  let current = "tools";

  const bar = tabs(SECTIONS, {
    selected: current,
    onSelect: async (id) => {
      current = id;
      bar.querySelectorAll("button").forEach((button, index) => {
        button.setAttribute("aria-selected", String(SECTIONS[index].id === id));
      });
      await draw();
    },
  });

  async function draw() {
    panel.replaceChildren(el("p", { class: "muted", text: "Loading…" }));
    try {
      const renderers = { tools, skills, workflows, connectors };
      panel.replaceChildren(await renderers[current]());
    } catch (error) {
      panel.replaceChildren(el("p", { class: "muted", text: error.message }));
      reportError(error, "Could not load that section");
    }
  }

  root.append(bar, panel);
  await draw();
}

async function tools() {
  const data = await api.get("/tools");
  return card(
    `${data.count} tools`,
    el("p", {
      class: "hint",
      text: "Danger level decides whether a call needs a human decision. The default handler defers rather than denying, so a run pauses for an approver instead of failing.",
    }),
    table(
      [
        { label: "Tool", render: (t) => el("code", { text: t.name }) },
        {
          label: "Danger",
          render: (t) => badge(t.danger ?? "safe", DANGER_TONE[t.danger] ?? ""),
        },
        {
          label: "Approval",
          render: (t) => (t.requires_approval ? badge("always gated", "bad") : "—"),
        },
        { label: "Permissions", render: (t) => (t.required_permissions ?? []).join(", ") || "—" },
        { label: "Description", render: (t) => el("span", { class: "muted", text: t.description ?? "" }) },
        {
          label: "",
          render: (t) => el("button", { text: "Invoke", onClick: () => invokeTool(t) }),
        },
      ],
      data.tools ?? [],
    ),
  );
}

function invokeTool(tool) {
  const args = el("textarea", { class: "code", text: "{}" });
  const output = el("pre", { class: "output", text: "" });
  modal(
    `Invoke ${tool.name}`,
    el(
      "div",
      {},
      el("p", { class: "lede", text: tool.description ?? "" }),
      field("Arguments (JSON)", args),
      output,
    ),
    [
      {
        label: "Run",
        run: async () => {
          let parsed;
          try {
            parsed = JSON.parse(args.value || "{}");
          } catch {
            toast("Arguments must be valid JSON", { tone: "error" });
            return;
          }
          try {
            const result = await api.post(`/tools/${tool.name}/invoke`, { arguments: parsed });
            output.textContent = JSON.stringify(result, null, 2);
            toast(`${tool.name}: ${result.status}`, {
              tone: result.status === "success" ? "success" : "error",
            });
          } catch (error) {
            output.textContent = error.message;
            reportError(error, "The tool call failed");
          }
        },
      },
    ],
  );
}

async function skills() {
  const data = await api.get("/skills");
  return card(
    `${data.count ?? (data.skills ?? []).length} skills`,
    table(
      [
        { label: "Skill", render: (s) => el("code", { text: s.name }) },
        { label: "Version", render: (s) => s.version },
        { label: "Category", render: (s) => s.category ?? "—" },
        { label: "Stability", render: (s) => badge(s.stability ?? "experimental") },
        { label: "Owner", render: (s) => s.owner ?? "—" },
        { label: "Description", render: (s) => el("span", { class: "muted", text: s.description ?? "" }) },
      ],
      data.skills ?? [],
    ),
  );
}

async function workflows() {
  const list = await api.get("/workflows");
  const wrapper = el("div", {});
  wrapper.append(
    card(
      `${list.length} workflows`,
      table(
        [
          { label: "Workflow", render: (w) => el("code", { text: w.name }) },
          { label: "Version", render: (w) => w.version },
          { label: "Steps", render: (w) => w.steps },
          { label: "Description", render: (w) => el("span", { class: "muted", text: w.description ?? "" }) },
          {
            label: "",
            render: (w) =>
              el("button", {
                text: "Execution plan",
                onClick: async (event) => {
                  try {
                    const graph = await withBusy(event.target, () =>
                      api.get(`/workflows/${w.name}/graph`),
                    );
                    modal(
                      `${w.name} — execution plan`,
                      el(
                        "div",
                        {},
                        el("p", {
                          class: "lede",
                          text: "Steps on the same level run concurrently. Reading a step's output without declaring it in depends_on is rejected at load time — that combination is a race, not a shortcut.",
                        }),
                        el("pre", { class: "output", text: JSON.stringify(graph, null, 2) }),
                      ),
                    );
                  } catch (error) {
                    reportError(error, "Could not load the plan");
                  }
                },
              }),
          },
        ],
        list,
      ),
    ),
  );
  return wrapper;
}

async function connectors() {
  const [list, health] = await Promise.all([
    api.get("/connectors"),
    api.get("/connectors/health").catch(() => ({})),
  ]);
  return card(
    `${list.count} connectors`,
    table(
      [
        { label: "Connector", render: (c) => el("code", { text: c.name }) },
        { label: "Type", render: (c) => c.type },
        { label: "State", render: (c) => badge(c.state, c.state === "ready" ? "ok" : "warn") },
        { label: "Provides tools", render: (c) => (c.provides_tools ? "yes" : "no") },
        {
          label: "Health",
          render: (c) => {
            const result = health[c.name];
            return result
              ? badge(result.status, result.status === "healthy" ? "ok" : "bad")
              : badge("unknown");
          },
        },
      ],
      list.connectors ?? [],
      { emptyMessage: "No outbound connectors are configured." },
    ),
  );
}
