/* Form builder: turn a spreadsheet somebody already fills in into a form. */

import { api } from "../api.js";
import { badge, card, el, field, reportError, table, toast, withBusy } from "../ui.js";

export async function render(root, _params) {
  root.append(
    el(
      "div",
      { class: "page-head" },
      el("h1", { text: "Form builder" }),
      el("p", {
        class: "lede",
        text: "Upload the spreadsheet you fill in by hand today. Structure is read deterministically — header row, column types, picklists, how consistently each column was filled — and the model only writes the labels, descriptions, and the reason each field is asked for.",
      }),
    ),
  );

  const fileInput = el("input", {
    type: "file",
    accept: ".xlsx,.xlsm,.csv,.json",
    style: "display:none",
  });
  const nameInput = el("input", { type: "text", placeholder: "leave blank to infer from the file" });
  const dropZone = el(
    "div",
    {
      class: "drop-zone",
      tabindex: "0",
      role: "button",
      text: "Drop an .xlsx, .csv, or .json sample here, or click to choose one",
      onClick: () => fileInput.click(),
      onKeydown: (e) => (e.key === "Enter" || e.key === " ") && fileInput.click(),
    },
  );
  const result = el("div", {});

  for (const type of ["dragenter", "dragover"]) {
    dropZone.addEventListener(type, (event) => {
      event.preventDefault();
      dropZone.classList.add("hover");
    });
  }
  for (const type of ["dragleave", "drop"]) {
    dropZone.addEventListener(type, () => dropZone.classList.remove("hover"));
  }
  dropZone.addEventListener("drop", (event) => {
    event.preventDefault();
    const [file] = event.dataTransfer.files;
    if (file) infer(file, nameInput.value.trim(), result);
  });
  fileInput.addEventListener("change", () => {
    const [file] = fileInput.files;
    if (file) infer(file, nameInput.value.trim(), result);
  });

  root.append(
    card(
      "1. Upload a sample",
      field("Form name", nameInput, "snake_case. Blank derives one from the filename."),
      dropZone,
      fileInput,
    ),
    result,
  );
}

async function infer(file, formName, result) {
  const body = new FormData();
  body.append("file", file);

  result.replaceChildren(card(null, el("p", { class: "muted", text: `Reading ${file.name}…` })));

  let report;
  try {
    report = await withBusy(result, () =>
      api.upload("/forms/infer", body, { form_name: formName || undefined, register: true }),
    );
  } catch (error) {
    result.replaceChildren(
      card("That sample could not be read", el("p", { class: "lede", text: error.message })),
    );
    reportError(error, "Inference failed");
    return;
  }

  const definition = report.definition;
  toast(`Draft ${definition.name} v${definition.version} created`, { tone: "success" });
  result.replaceChildren(renderReport(report, definition));
}

function renderReport(report, definition) {
  const wrapper = el("div", {});

  wrapper.append(
    card(
      "2. What was inferred",
      el(
        "div",
        { class: "row" },
        badge("draft", "warn"),
        el("code", { text: `${definition.name}@${definition.version}` }),
        el("span", {
          class: "muted",
          text: `${report.fields} fields in ${report.sections} section(s), from ${report.source || "the sample"}`,
        }),
      ),
      ...(report.warnings ?? []).map((warning) =>
        el("p", { class: "hint" }, badge("check", "warn"), el("span", { text: ` ${warning}` })),
      ),
      el("p", {
        class: "hint",
        text: "Registered as a draft and deliberately not activated — the questions below should be answered before anyone fills it in.",
      }),
      table(
        [
          { label: "Field", render: (f) => el("strong", { text: f.label }) },
          { label: "Id", render: (f) => el("code", { text: f.id }) },
          { label: "Type", render: (f) => f.type },
          { label: "Importance", render: (f) => badge(f.importance) },
          { label: "Options", render: (f) => (f.options?.length ? f.options.join(", ") : "—") },
          { label: "Rationale", render: (f) => el("span", { class: "muted", text: f.rationale || "—" }) },
        ],
        definition.sections.flatMap((s) => s.fields),
      ),
    ),
  );

  const questions = report.questions ?? [];
  const instructions = el("textarea", {
    placeholder:
      "Answer in plain language, e.g. “cost centre is optional, priority should allow 'urgent' too, and add a field for the rollback plan”",
  });

  wrapper.append(
    card(
      "3. What the facilitator could not settle",
      questions.length
        ? el(
            "ul",
            {},
            ...questions.map((question) =>
              el("li", { text: typeof question === "string" ? question : question.question }),
            ),
          )
        : el("p", { class: "muted", text: "Nothing — the sample was unambiguous." }),
      instructions,
      el(
        "div",
        { class: "row", style: "margin-top:10px" },
        el("button", {
          class: "primary",
          text: "Apply changes",
          onClick: async (event) => {
            if (!instructions.value.trim()) {
              toast("Describe what to change first");
              return;
            }
            try {
              const updated = await withBusy(event.target, () =>
                api.post(`/forms/${definition.name}/refine`, { instructions: instructions.value }),
              );
              toast(`Draft updated to v${updated.version}`, { tone: "success" });
              window.location.hash = `#/forms/${definition.name}`;
            } catch (error) {
              reportError(error, "Could not apply those changes");
            }
          },
        }),
        el("button", {
          text: "Skip and publish",
          onClick: async () => {
            try {
              await api.post(`/forms/${definition.name}/versions/${definition.version}/activate`);
              toast("Published — it is now the active version", { tone: "success" });
              window.location.hash = `#/forms/${definition.name}`;
            } catch (error) {
              reportError(error, "Could not publish the draft");
            }
          },
        }),
        el("a", { href: `#/forms/${definition.name}`, class: "button", text: "Review the draft" }),
      ),
    ),
  );

  return wrapper;
}
