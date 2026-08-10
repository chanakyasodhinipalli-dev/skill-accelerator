/* Console-local state.
 *
 * Only preferences live here — who you are acting as, which model you pinned,
 * the theme, and the assistant thread id. Everything else is read from the API
 * on demand.
 *
 * That is deliberate. A console that caches domain objects starts showing a
 * form version, an approval status, or a session's progress that no longer
 * matches the server, and the disagreement always surfaces at the worst moment.
 * These records change under you — another approver signs off, a new version is
 * published — so they are fetched, not remembered.
 */

const KEY = "sa-console";

function load() {
  try {
    return JSON.parse(window.localStorage.getItem(KEY) ?? "{}");
  } catch {
    return {};
  }
}

const stored = load();

const defaults = {
  participant: "",
  theme: "auto",
  profileOverride: null,
  assistantConversationId: null,
};

/** Persisted preferences, saved on every write. */
export const state = new Proxy(
  { ...defaults, ...stored, profiles: [], activeProfile: null },
  {
    set(target, key, value) {
      target[key] = value;
      if (key in defaults) {
        const persisted = Object.fromEntries(Object.keys(defaults).map((k) => [k, target[k]]));
        try {
          window.localStorage.setItem(KEY, JSON.stringify(persisted));
        } catch {
          /* private browsing: preferences simply do not persist */
        }
      }
      return true;
    },
  },
);
