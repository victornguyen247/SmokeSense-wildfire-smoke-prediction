import { useState, type FormEvent } from "react";

import { subscribeToAlerts } from "../../api/alerts";
import { ApiError } from "../../api/client";
import type { PointQuery } from "../../api/forecast";

type AlertSignupProps = {
  /** The location the card shows: the subscription is for exactly this place. */
  query: PointQuery;
  /** How the card names it, e.g. "ZIP 95926". */
  label: string;
};

type State =
  | { status: "idle" }
  | { status: "submitting" }
  | { status: "sent"; email: string }
  | { status: "error"; message: string; field: boolean };

// Format only; the API decides (400 invalid_query).
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** Plain-language messages for the API's errors (docs/alerts.md, section 8). */
function errorState(err: unknown): Extract<State, { status: "error" }> {
  const code = err instanceof ApiError ? err.code : null;
  if (code === "invalid_query") return { status: "error", message: "Check the email address.", field: true };
  if (code === "out_of_scope") return { status: "error", message: "SmokeSense only covers California.", field: false };
  if (code === "zip_not_found") return { status: "error", message: "We couldn't find that ZIP code.", field: false };
  return { status: "error", message: "Something went wrong. Please try again.", field: false };
}

/**
 * WEB-05 part A: "Email me alerts for this location", under the location card. Only an
 * email field: the location is the card's. Every accepted request shows the same "check
 * your email" message, so the form never reveals who has signed up. The address stays in
 * this component's state; it is never stored or logged.
 */
export function AlertSignup({ query, label }: AlertSignupProps) {
  const [email, setEmail] = useState("");
  const [state, setState] = useState<State>({ status: "idle" });

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const address = email.trim();
    if (!EMAIL_PATTERN.test(address)) {
      setState({ status: "error", message: "Enter an email address, e.g. name@example.com.", field: true });
      return;
    }
    setState({ status: "submitting" });
    try {
      await subscribeToAlerts({ email: address, ...query });
      setState({ status: "sent", email: address });
    } catch (err) {
      setState(errorState(err));
    }
  };

  if (state.status === "sent") {
    return (
      <section className="alert-signup" aria-labelledby="alert-signup-heading">
        <h3 id="alert-signup-heading" className="panel-section__subheading">
          Email alerts
        </h3>
        <div className="alert-signup__sent" role="status">
          <p className="alert-signup__sent-title">Check your email</p>
          <p>
            We sent a confirmation link to <strong>{state.email}</strong>. The link expires in 48 hours.
          </p>
        </div>
        <button type="button" className="button button--small" onClick={() => setState({ status: "idle" })}>
          Use a different email
        </button>
      </section>
    );
  }

  const fieldError = state.status === "error" && state.field ? state.message : null;
  const formError = state.status === "error" && !state.field ? state.message : null;

  return (
    <section className="alert-signup" aria-labelledby="alert-signup-heading">
      <h3 id="alert-signup-heading" className="panel-section__subheading">
        Email me alerts for this location
      </h3>
      <p className="alert-signup__location">Alerts for {label}.</p>
      <form className="alert-signup__form" onSubmit={submit} noValidate>
        <label htmlFor="alert-email" className="visually-hidden">
          Email address
        </label>
        <input
          id="alert-email"
          className="location-search__input"
          type="email"
          inputMode="email"
          autoComplete="email"
          placeholder="Email address"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          aria-invalid={fieldError !== null}
          aria-describedby={fieldError ? "alert-email-error" : undefined}
        />
        <button type="submit" className="button" disabled={state.status === "submitting"}>
          {state.status === "submitting" ? "Sending…" : "Sign up"}
        </button>
      </form>
      {fieldError && (
        <p id="alert-email-error" className="location-search__error" role="alert">
          {fieldError}
        </p>
      )}
      {formError && (
        <p className="location-search__error" role="alert">
          {formError}
        </p>
      )}
      <p className="alert-signup__experimental">
        Alerts are an experimental model estimate, not an official warning.
      </p>
      <p className="alert-signup__privacy">
        We use your email and the location you choose only to send SmokeSense smoke alerts. We store your
        email and the forecast area (a 12.5 km grid square, plus your ZIP or a point rounded to about 1 km),
        never your name or exact location. Every alert has a one-click unsubscribe link, and unsubscribing
        deletes your data immediately. SmokeSense is a student project: all subscriber data is deleted by
        December 11, 2026.
      </p>
    </section>
  );
}
