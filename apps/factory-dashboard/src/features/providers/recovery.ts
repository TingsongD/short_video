// Also explains older paused records without mutating or resuming them.
const MESSAGES: Record<string, string> = {
  reauth_required: "Reconnect the configured Google account using Application Default Credentials, then use Providers → Re-check readiness.",
  no_credentials: "Configure Google Application Default Credentials for the approved account, then re-check readiness.",
  expired: "Refresh the configured Google credentials, then re-check readiness.",
  credential_transport_failed: "Check the network connection to Google authentication, then re-check readiness.",
  credential_dependency_missing: "Install the project's Google authentication dependencies in the service environment, restart the service, then re-check readiness.",
  credential_refresh_failed: "Google credential refresh failed. Check the configured account and authentication service, then re-check readiness.",
  loader_failed: "The older generic credential error does not prove whether a request was sent. Check provider readiness and review the attempt evidence.",
};

export function credentialRecovery(detail: string = ""): string | undefined {
  const reason = detail.trim().split(/\s+/).pop() || "";
  const message = MESSAGES[reason];
  return message ? `${message} Reconcile any unknown attempt before Resume; reconnecting does not release a budget hold.` : undefined;
}

export function analysisRecovery(detail: string = ""): string | undefined {
  const reason = detail.trim().split(/\s+/).pop() || "";
  if (!["malformed_analysis", "invalid_analysis_timing"].includes(reason)) return;
  return "The analysis response failed format or timing checks. This request is potentially billable. " +
    "Review the saved response and validation event; an operator must reconcile the completed " +
    "unusable attempt and settle its estimate before Resume. Do not release it as uncharged " +
    "or repeatedly retry. Scene and passage timing must remain valid.";
}
