# The operator console

A browser UI over the platform API. Built to be *used* rather than demonstrated:
every screen drives the real endpoints, so anything that works here works from a
client, and anything broken here is broken for everyone.

```bash
make ui                 # http://127.0.0.1:8100
```

That is the whole setup. The platform API is mounted in the same process, so
there is one command, one port, no CORS, and nothing to keep in sync.

## Two deployment modes

| | Embedded (default) | Remote |
|---|---|---|
| API | Mounted at `/api` in this process | Proxied to `SA_CONSOLE_API_BASE_URL` |
| Use for | Local work, demos, a live test harness | An API deployed and scaled separately |
| Credential | Whatever the process has | Held server-side, attached on the way out |

```bash
sa-console --api https://sa.internal      # remote mode
SA_CONSOLE_API_KEY=... sa-console --api https://sa.internal
```

Either way the browser talks only to the console's own origin. There is no second
base URL in the front end and no CORS configuration.

In remote mode the console is the trust boundary: `SA_CONSOLE_API_KEY` is
attached to the upstream request server-side and never reaches the browser.

One implementation detail worth knowing: Starlette does not forward lifespan
events to a mounted sub-application, so the console runs the platform's bootstrap
itself. Without that the API would serve requests against an empty registry.

## The screens

**Overview** — counts, what is waiting on you, which profile is answering, and
the aggregated health checks.

**Forms** — the catalogue, one definition in full (fields, importance, rationale,
conditional guards, sensitivity), and version history. Each row says which
**kind** it is and what it asks for in the units it is measured in — an
agreement form reported as "0 required / 0 fields" reads as an empty form
somebody forgot to finish — and its button says *Review and accept* rather than
*Fill in*. Drafts can be activated or
refined; published versions fork rather than being edited. Two blocks answer
questions people ask before they start rather than after: **Agreements** — what
they will be asked to accept, in the wording they will see it — and **When it
can't answer**, which lists the reference notes the assistant may answer from and
the teams a question gets routed to when they do not cover it.

**Form builder** — drop in the spreadsheet you fill in by hand. Structure is read
deterministically; the model writes labels, descriptions, and the reason each
field is asked for. You get a **draft** plus the questions the facilitator could
not settle, and answer them in plain language before publishing.

**Session** — the workspace. Chat on the left, the form's live state on the
right. That layout is the point: a conversational intake tool that hides the
field list asks people to trust that their answers landed somewhere. Each field
shows its value, who said it, on which channel, and with what confidence.

Four things on this screen exist because the conversation alone would leave them
invisible:

* **Before we start** — the consent gate. It shows each agreement's wording as
  the form declares it, with **I agree** and **I can't accept this** buttons. The
  wording comes from the definition rather than from the chat bubble it was
  announced in: what somebody accepts has to be the declared text, and reading it
  back out of a transcript would put a copy between the two. Nothing is recorded
  against the session until this is settled — including an ingested email.
* **Asking about now** — the fields the current question covers, highlighted in
  place. Topics are grouped by how fields relate rather than by the section they
  were filed in, so one question routinely spans two cards. Without the marker
  that reads as the assistant wandering; with it you can see the group it chose.
* **Agreements** — every declared agreement and where it stands, with the stored
  wording, who decided, when, and what they typed. A decision is only offered for
  agreements the submission has actually reached: a confirmation of accuracy is
  undecided from the first turn and refused until there is something to confirm.
* **Questions raised** — what the participant asked and what became of it:
  answered from the form, from its reference notes, or routed to a team. An open
  one carries a **They came back** action that records the answer and closes it.

Accepting from this screen makes the conversation continue: the engine puts the
next term, or asks its next question, and it appears in the chat. A gate that
opens without anyone saying anything leaves the conversation waiting for a
message and the person waiting for a question — and on an agreement form it
empties the consent panel while four clauses are still outstanding, which looks
finished when it is not.

On an **agreement form** the same screen measures itself differently: the
progress bar counts agreements rather than fields, the header says *all agreed*
rather than *required fields complete*, and the ingest panel is hidden when there
are no fields to mine a thread for. Terms arrive one at a time, each carrying its
place in the sequence, and **Skip this one** is disabled while one is on the
table — skipping is not one of the answers to a term.

**Artifacts** — pending reviews, approve or reject, download, and verify that a
baseline's bytes still match the checksum recorded at sign-off.

**Assistant** — ask about any form conversation across every session, with
citations you can click through to the record.

**Models** — profiles with live counters, activate, probe, register a new one,
and run one prompt across several vendors side by side.

**Platform** — skills, tools with their danger levels, workflow execution plans,
and connector health. Tools can be invoked from here, which answers "does this
actually work" without writing a client.

## Filling a form from an email

The Session screen's ingest panel takes an `.eml` file plus any extra
attachments. Attachments inside the message are read automatically; the separate
upload exists because mail clients drop attachments on forward far more often
than people expect.

Readable formats: `xlsx`, `csv`, `docx`, `pdf`, `json`, `html`, `txt`, `md`, and
a forwarded `.eml` (one level deep).

Three behaviours are worth stating because they are what make this trustworthy:

* **Quoted history is cut before extraction.** A reply that quotes the original
  question would otherwise let the extractor re-read superseded values and
  overwrite current answers with stale ones.
* **A two-column sheet is read as `Label: value`,** which the deterministic
  matcher understands — so an attached key/value spreadsheet fills the form with
  no model involved at all.
* **An unreadable attachment is reported, not dropped.** The response names every
  file and whether its text could be read. Silently ignoring one is how a form
  ends up confidently wrong.

Outlook `.msg` is a compound binary format and is rejected with an explanation of
how to export MIME instead — better than treating the binary as a body.

Ingest is behind the same consent gate as the conversation, and refuses with the
outstanding agreements named. Mining a thread stores the participant's words
exactly as typing them would, and a terms-of-recording agreement that the upload
path walks around is not a gate, it is a notice.

## Choosing the model from the UI

The header has a model picker. Selecting a profile pins `X-LLM-Profile` on every
request **this console** makes, which is how you try a vendor without changing
anything for anyone else. Changing the server default for everyone is a button on
the Models page.

With no credential configured at all, pick **Deterministic (no model)**. Every
screen and every flow still works; only generated wording falls back to fixed
phrasing.

## Identity

The header's "Acting as" field is the participant attributed to sessions,
messages, and approvals. It is a convenience for testing, not authentication:
the platform's identity comes from `get_principal`, and a user-facing deployment
replaces that dependency with an OIDC verifier. Everything downstream already
consumes `Principal`.

The approval rules are enforced server-side regardless — a contributor cannot
approve their own submission, and recording a decision under someone else's name
needs `forms:approve:on_behalf`.

## The front end

Vanilla ES modules, one stylesheet, no build step and no framework. `npm` is not
in the loop, which means the console is deployable anywhere the Python package
is and there is no lockfile to keep current.

Two conventions hold it together:

* **Elements are built from data, never from string templates.** The console
  renders user-supplied text — form values, transcripts, email bodies — and
  building nodes with `textContent` makes injection structurally impossible
  rather than a review item on every call.
* **Almost nothing is cached.** Only preferences live in the browser. Form
  versions, session progress, and approval status change under you, so they are
  fetched rather than remembered.

## Configuration

| Variable | Default | |
|---|---|---|
| `SA_CONSOLE_PORT` | `8100` | |
| `SA_CONSOLE_API_BASE_URL` | unset | Set to proxy to a remote API |
| `SA_CONSOLE_API_KEY` | unset | Forwarded upstream; never sent to the browser |
| `SA_CONSOLE_ENVIRONMENT_BANNER` | unset | Shown in the header, so nobody demos against production by accident |
| `SA_CONSOLE_DEFAULT_PARTICIPANT` | `operator` | |
| `SA_CONSOLE_THEME` | `auto` | `auto` follows the OS |
