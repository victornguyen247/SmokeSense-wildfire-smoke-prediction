// The email alert endpoints (docs/alerts.md, section 2).
//
// Their POST paths join docs/api/openapi.yaml with API-05 (#111). Until then these use
// `postJson` with the spec's request and response schemas, so errors are the usual
// ApiError. Switch to apiClient.POST once the paths are in the spec.

import { postJson } from "./client";
import type {
  AlertConfirmResult,
  AlertSubscribeAccepted,
  AlertSubscribeRequest,
  AlertUnsubscribeResult,
} from "./models";

/** Start a double opt-in sign-up. Every valid request gets the same 202, by design. */
export function subscribeToAlerts(
  request: AlertSubscribeRequest,
  signal?: AbortSignal,
): Promise<AlertSubscribeAccepted> {
  return postJson("/api/v1/alerts/subscriptions", request, signal);
}

/** Confirm a sign-up with the token from the confirmation email. */
export function confirmAlerts(token: string, signal?: AbortSignal): Promise<AlertConfirmResult> {
  return postJson("/api/v1/alerts/confirm", { token }, signal);
}

/** Unsubscribe (and delete the subscription) with the token from an alert email. */
export function unsubscribeFromAlerts(token: string, signal?: AbortSignal): Promise<AlertUnsubscribeResult> {
  return postJson("/api/v1/alerts/unsubscribe", { token }, signal);
}
