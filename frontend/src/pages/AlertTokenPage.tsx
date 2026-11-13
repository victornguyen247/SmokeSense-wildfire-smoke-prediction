import { useEffect, useRef, useState } from "react";

import { confirmAlerts, unsubscribeFromAlerts } from "../api/alerts";
import { ApiError } from "../api/client";
import { Spinner } from "../components/ui/Spinner";

type Kind = "confirm" | "unsubscribe";

type Result = { title: string; body: string; ok: boolean };

// docs/alerts.md, section 6c.
const RESULTS = {
  confirmed: {
    ok: true,
    title: "You're signed up.",
    body: "We'll email you when SmokeSense's model expects smoke unhealthy for sensitive groups at your location, at most once a day. Every email has a one-click unsubscribe link.",
  },
  already_confirmed: { ok: true, title: "You're already signed up.", body: "Nothing else to do." },
  token_expired: {
    ok: false,
    title: "This link has expired.",
    body: "Confirmation links last 48 hours. Sign up again from the map to get a new one.",
  },
  confirm_invalid: {
    ok: false,
    title: "This link isn't valid.",
    body: "It may have been replaced by a newer sign-up. Sign up again from the map.",
  },
  unsubscribed: {
    ok: true,
    title: "You're unsubscribed.",
    body: "Your email address and location have been deleted. You won't get any more SmokeSense alerts.",
  },
  unsubscribe_invalid: {
    ok: false,
    title: "This link isn't valid.",
    body: "Check that you copied the whole link from the email.",
  },
  failed: { ok: false, title: "Something went wrong.", body: "Please try again in a minute." },
} satisfies Record<string, Result>;

// The token may come after "#" (`#token=…`) or in the query (`?token=…`). The fragment is
// never sent to a server, so it can't end up in an access log or a Referer header.
const fragmentParams = (url: URL) => new URLSearchParams(url.hash.slice(1));

function readToken(): string | null {
  const url = new URL(window.location.href);
  return fragmentParams(url).get("token") ?? url.searchParams.get("token");
}

/** Take the token out of the address bar, so it isn't kept in history or shared by accident. */
function stripToken(): void {
  const url = new URL(window.location.href);
  const fragment = fragmentParams(url);
  if (!url.searchParams.has("token") && !fragment.has("token")) return;
  url.searchParams.delete("token");
  fragment.delete("token");
  url.hash = fragment.toString();
  window.history.replaceState(window.history.state, "", url.pathname + url.search + url.hash);
}

async function submit(kind: Kind, token: string): Promise<Result> {
  try {
    if (kind === "confirm") return RESULTS[(await confirmAlerts(token)).status];
    await unsubscribeFromAlerts(token);
    return RESULTS.unsubscribed;
  } catch (err) {
    const code = err instanceof ApiError ? err.code : null;
    if (code === "token_expired" && kind === "confirm") return RESULTS.token_expired;
    if (code === "invalid_token") return kind === "confirm" ? RESULTS.confirm_invalid : RESULTS.unsubscribe_invalid;
    return RESULTS.failed;
  }
}

/**
 * WEB-05 part B: `/alerts/confirm` and `/alerts/unsubscribe` with the token, the pages the
 * email links open. Opening the page changes nothing by itself until it POSTs the token,
 * exactly once (docs/alerts.md, "Email links never change state").
 */
export function AlertTokenPage({ kind }: { kind: Kind }) {
  const [token] = useState(readToken);
  const [result, setResult] = useState<Result | null>(() =>
    token ? null : kind === "confirm" ? RESULTS.confirm_invalid : RESULTS.unsubscribe_invalid,
  );
  // StrictMode runs effects twice in development; the token must be sent only once.
  const sent = useRef(false);

  useEffect(() => {
    stripToken();
    if (!token || sent.current) return;
    sent.current = true;
    void submit(kind, token).then(setResult);
  }, [kind, token]);

  return (
    <div className="app">
      <header className="app-header">
        <h1 className="app-header__title">SmokeSense</h1>
        <p className="app-header__tagline">{kind === "confirm" ? "Confirm email alerts" : "Unsubscribe from email alerts"}</p>
      </header>
      <main className="token-page">
        <section className="token-page__card" aria-live="polite">
          {result === null ? (
            <Spinner label={kind === "confirm" ? "Confirming your sign-up…" : "Unsubscribing…"} />
          ) : (
            <>
              <h2 className={result.ok ? "token-page__title" : "token-page__title token-page__title--problem"}>
                {result.title}
              </h2>
              <p>{result.body}</p>
            </>
          )}
          <a href="/" className="button token-page__back">
            Back to the map
          </a>
        </section>
      </main>
    </div>
  );
}
