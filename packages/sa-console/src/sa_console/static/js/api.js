/* Platform API client.
 *
 * The console always talks to its own origin at /api — mounted in process or
 * proxied to a remote deployment. The front end never knows which, so there is
 * no base URL to configure and no CORS to get wrong.
 *
 * Errors arrive as RFC 7807 problem documents. They are unwrapped into a single
 * ApiError so every caller can show `error.message` without inspecting the
 * envelope, while keeping `code`, `details`, and `correlationId` for the cases
 * that need them.
 */

const BASE = "/api";

export class ApiError extends Error {
  constructor(message, { status = 0, code = "error", details = null, correlationId = null } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
    this.correlationId = correlationId;
  }

  /** Field-level messages from a 422, flattened for display. */
  get fieldErrors() {
    const raw = this.details?.errors ?? this.details?.validation ?? null;
    if (!Array.isArray(raw)) return [];
    return raw.map((e) => `${(e.loc ?? []).slice(1).join(".") || "body"}: ${e.msg ?? e.message}`);
  }
}

/** Extra headers applied to every request, e.g. the selected model profile. */
const ambient = new Map();

export function setHeader(name, value) {
  if (value === null || value === undefined || value === "") ambient.delete(name);
  else ambient.set(name, value);
}

function buildUrl(path, query) {
  const url = new URL(`${BASE}${path}`, window.location.origin);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== "") url.searchParams.set(key, value);
  }
  return url.toString().slice(window.location.origin.length);
}

async function toError(response) {
  let body = null;
  try {
    body = await response.json();
  } catch {
    /* a proxy or gateway error may not be JSON at all */
  }
  const message =
    body?.detail ?? body?.error?.message ?? body?.message ?? `${response.status} ${response.statusText}`;
  return new ApiError(message, {
    status: response.status,
    code: body?.code ?? body?.error?.code ?? "http_error",
    details: body?.details ?? null,
    correlationId: body?.correlation_id ?? response.headers.get("x-correlation-id"),
  });
}

async function request(method, path, { body, query, formData, accept } = {}) {
  const headers = { accept: accept ?? "application/json", ...Object.fromEntries(ambient) };
  const init = { method, headers };

  if (formData) {
    // Deliberately no content-type: the browser must set the multipart
    // boundary itself, and setting it by hand breaks every upload.
    init.body = formData;
  } else if (body !== undefined) {
    headers["content-type"] = "application/json";
    init.body = JSON.stringify(body);
  }

  let response;
  try {
    response = await fetch(buildUrl(path, query), init);
  } catch (cause) {
    throw new ApiError("The console could not reach the platform API.", {
      code: "network_error",
      details: { cause: String(cause) },
    });
  }

  if (!response.ok) throw await toError(response);
  if (response.status === 204) return null;

  const type = response.headers.get("content-type") ?? "";
  if (type.includes("application/json")) return response.json();
  if (accept === "blob") return response.blob();
  return response.text();
}

export const api = {
  get: (path, query) => request("GET", path, { query }),
  post: (path, body, query) => request("POST", path, { body, query }),
  put: (path, body) => request("PUT", path, { body }),
  patch: (path, body) => request("PATCH", path, { body }),
  del: (path, query) => request("DELETE", path, { query }),
  upload: (path, formData, query) => request("POST", path, { formData, query }),
  blob: (path) => request("GET", path, { accept: "blob" }),
};

/** Download an artifact, preserving the filename the server chose. */
export async function download(path, filename) {
  const blob = await api.blob(path);
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  // Revoking immediately can cancel the download in some browsers.
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}
