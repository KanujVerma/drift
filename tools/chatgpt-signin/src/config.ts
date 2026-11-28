/** Drift-specific names and safe, non-secret diagnostics for the vendored sign-in. */
export const APP_NAME = "drift";
export const APP_TITLE = "Drift";
export const REQUEST_MS = { signIn: 30_000 } as const;
export const SIGN_IN = {
  refreshMarginSeconds: 300,
  retryAfterSeconds: 60,
  lockWaitMs: 30_000,
  browserMs: 600_000,
  assumedTokenSeconds: 3_600,
  clockLeewaySeconds: 5,
  lockPollMs: 100,
  callbackCloseMs: 1_000,
} as const;

// Do not include provider-controlled text or credentials in diagnostics.
export function message(key: string, _details?: object): string {
  if (key === "signin.openAddress") return "Open this address to authorize Drift:";
  if (key === "signin.returnToTerminal") return "Return to Drift to finish sign-in.";
  if (key === "signin.pasteIfNeeded") return "Use the loopback callback on this computer.";
  return key;
}
