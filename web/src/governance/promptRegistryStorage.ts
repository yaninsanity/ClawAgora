/** Session persistence for Governance panel "Prompt registry" expand/collapse. */

const SESSION_PROMPT_REGISTRY_OPEN = "clawagora.gov.promptRegistryOpen";

export function loadPromptRegistryOpen(): boolean {
  if (typeof window === "undefined") return false;
  try {
    const v = window.sessionStorage.getItem(SESSION_PROMPT_REGISTRY_OPEN);
    if (v === "1") return true;
    if (v === "0") return false;
  } catch {
    /* storage unavailable */
  }
  return false;
}

export function savePromptRegistryOpen(open: boolean): void {
  try {
    window.sessionStorage.setItem(SESSION_PROMPT_REGISTRY_OPEN, open ? "1" : "0");
  } catch {
    /* quota / private mode */
  }
}
