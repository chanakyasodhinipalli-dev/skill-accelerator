/* Artifacts: review, approve, baseline, and prove a baseline is intact. */

import { api, download } from "../api.js";
import { badge, card, el, field, modal, reportError, table, toast } from "../ui.js";
import { state } from "../state.js";

const TONE = {
  draft: "",
  in_review: "warn",
  changes_requested: "bad",
  approved: "ok",
  baselined: "ok",
  superseded: "",
};

export async function render(root, _params) {
  root.append(
    el(
      "div",
      { class: "page-head" },
      el("h1", { text: "Artifacts" }),
      el("p", {
        class: "lede",
        text: "Approving baselines the document: the bytes are checksummed, the session locks, and regenerating produces a new revision rather than editing the old one.",
      }),
    ),
  );

  const body = el("div", {});
  root.append(body);
  await load(body);
}

async function load(body) {
  const pending = await api.get("/forms/reviews/pending", { limit: 50 });

  body.replaceChildren(
    card(
      "Awaiting review",
      table(
        [
          { label: "Form", render: (r) => el("code", { text: r.form }) },
          { label: "Format", render: (r) => r.format },
          { label: "Revision", render: (r) => r.revision },
          { label: "Approvals", render: (r) => `${r.approvals}` },
          {
            label: "Session",
            render: (r) => el("a", { href: `#/session/${r.session_id}`, text: "open" }),
          },
          {
            label: "",
            render: (r) =>
              el(
                "div",
                { class: "row tight" },
                el("button", {
                  text: "Inspect",
                  onClick: () => inspect(r.artifact_id, body),
                }),
                el("button", {
                  class: "primary",
                  text: "Decide",
                  onClick: () => decide(r.artifact_id, body),
                }),
              ),
          },
        ],
        pending.artifacts,
        { emptyMessage: "Nothing is waiting for review." },
      ),
    ),
  );
}

async function inspect(artifactId, body) {
  try {
    const [record, verification] = await Promise.all([
      api.get(`/forms/artifacts/${artifactId}`),
      api.get(`/forms/artifacts/${artifactId}/verify`).catch(() => null),
    ]);

    modal(
      record.filename || "Artifact",
      el(
        "div",
        {},
        el(
          "div",
          { class: "row" },
          badge(record.status, TONE[record.status] ?? ""),
          el("code", { text: `${record.form_name}@${record.form_version}` }),
          badge(`revision ${record.revision}`),
          record.baselined_at ? badge("baselined", "ok") : null,
        ),
        el("p", { class: "mono muted", text: `sha256 ${record.checksum}` }),
        verification
          ? el(
              "p",
              {},
              verification.intact
                ? badge("bytes match the recorded checksum", "ok")
                : badge("TAMPERED — the stored bytes do not match", "bad"),
            )
          : null,
        record.approvals?.length
          ? table(
              [
                { label: "Approver", render: (a) => a.approver },
                { label: "Decision", render: (a) => badge(a.decision, a.decision === "approved" ? "ok" : "bad") },
                { label: "Comment", render: (a) => a.comment || "—" },
              ],
              record.approvals,
            )
          : el("p", { class: "muted", text: "No decisions recorded yet." }),
      ),
      [
        {
          label: "Download",
          class: "",
          run: () => download(`/forms/artifacts/${artifactId}/content`, record.filename),
        },
      ],
    );
  } catch (error) {
    reportError(error, "Could not load that artifact");
  }
}

function decide(artifactId, body) {
  const decision = el(
    "select",
    {},
    el("option", { value: "approved", text: "Approve — baseline this document" }),
    el("option", { value: "rejected", text: "Reject — send it back for changes" }),
  );
  const approver = el("input", { type: "text", value: state.participant });
  const comment = el("textarea", { placeholder: "Optional note recorded with the decision" });

  modal(
    "Record a review decision",
    el(
      "div",
      {},
      field("Decision", decision),
      field(
        "Approver",
        approver,
        "Recording a decision under someone else's name needs forms:approve:on_behalf — otherwise the caller's permissions would be checked against another person's name.",
      ),
      field("Comment", comment),
      el("p", {
        class: "hint",
        text: "A contributor cannot approve their own submission unless the form's policy allows it.",
      }),
    ),
    [
      {
        label: "Record",
        run: async () => {
          try {
            const result = await api.post(`/forms/artifacts/${artifactId}/decision`, {
              decision: decision.value,
              approver: approver.value || undefined,
              comment: comment.value,
            });
            toast(
              result.baselined
                ? "Approved and baselined"
                : `Recorded — status is now ${result.status}`,
              { tone: "success" },
            );
            await load(body);
          } catch (error) {
            reportError(error, "The decision was refused");
          }
        },
      },
    ],
  );
}
