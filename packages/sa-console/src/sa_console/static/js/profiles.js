/* Model profile selection for the header picker.
 *
 * In its own module rather than in the shell: the Models page needs to refresh
 * the picker after activating or registering a profile, and importing it from
 * the shell would make the shell and a view import each other.
 */

import { api, setHeader } from "./api.js";
import { clear, el, reportError } from "./ui.js";
import { state } from "./state.js";

/** Reload the picker from the API and re-apply the pinned profile, if any. */
export async function refreshProfiles() {
  const picker = document.getElementById("profile-picker");
  try {
    const data = await api.get("/providers");
    state.profiles = data.profiles;
    state.activeProfile = data.active;

    clear(picker);
    picker.append(el("option", { value: "", text: `Server default (${data.active})` }));
    for (const profile of data.profiles) {
      picker.append(
        el("option", {
          value: profile.name,
          text: `${profile.label}${profile.credential_present ? "" : " — no key"}`,
        }),
      );
    }

    // A pinned profile that has since been removed must not keep sending a
    // header naming it; fall back to the server default instead.
    const known = data.profiles.some((p) => p.name === state.profileOverride);
    if (state.profileOverride && !known) state.profileOverride = null;

    picker.value = state.profileOverride ?? "";
    setHeader("X-LLM-Profile", state.profileOverride);
  } catch (error) {
    clear(picker).append(el("option", { text: "unavailable" }));
    reportError(error, "Could not load model profiles");
  }
}
