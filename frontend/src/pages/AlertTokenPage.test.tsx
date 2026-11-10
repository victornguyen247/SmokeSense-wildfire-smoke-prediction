import { render, screen } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { StrictMode } from "react";
import { describe, expect, it, vi } from "vitest";

import { MOCK_ALERT_TOKENS } from "../mocks/handlers";
import { server } from "../test/setup";
import { AlertTokenPage } from "./AlertTokenPage";

function open(kind: "confirm" | "unsubscribe", token?: string) {
  window.history.replaceState(null, "", `/alerts/${kind}${token === undefined ? "" : `?token=${token}`}`);
  render(
    <StrictMode>
      <AlertTokenPage kind={kind} />
    </StrictMode>,
  );
}

const heading = async () => (await screen.findByRole("heading", { level: 2 })).textContent;

describe("AlertTokenPage", () => {
  it("confirms a sign-up, posting the token once, and removes it from the address bar", async () => {
    const posted = vi.fn();
    server.events.on("request:start", ({ request }) => posted(request.method, new URL(request.url).pathname));
    open("confirm", MOCK_ALERT_TOKENS.valid);
    expect(await heading()).toBe("You're signed up.");
    expect(window.location.search).toBe("");
    expect(posted).toHaveBeenCalledTimes(1);
    expect(posted).toHaveBeenCalledWith("POST", "/api/v1/alerts/confirm");
    server.events.removeAllListeners();
  });

  it("says when the sign-up was already confirmed", async () => {
    open("confirm", MOCK_ALERT_TOKENS.alreadyConfirmed);
    expect(await heading()).toBe("You're already signed up.");
  });

  it("says when the link expired", async () => {
    open("confirm", MOCK_ALERT_TOKENS.expired);
    expect(await heading()).toBe("This link has expired.");
    expect(screen.getByText(/Sign up again from the map/)).toBeTruthy();
  });

  it("says when the link isn't valid", async () => {
    open("confirm", "too-short");
    expect(await heading()).toBe("This link isn't valid.");
  });

  it("doesn't call the API without a token", async () => {
    const posted = vi.fn();
    server.events.on("request:start", posted);
    open("confirm");
    expect(await heading()).toBe("This link isn't valid.");
    expect(posted).not.toHaveBeenCalled();
    server.events.removeAllListeners();
  });

  it("unsubscribes", async () => {
    open("unsubscribe", MOCK_ALERT_TOKENS.valid);
    expect(await heading()).toBe("You're unsubscribed.");
    expect(window.location.search).toBe("");
  });

  it("says when an unsubscribe link isn't valid", async () => {
    open("unsubscribe", "too-short");
    expect(await heading()).toBe("This link isn't valid.");
    expect(screen.getByText(/copied the whole link/)).toBeTruthy();
  });

  it("asks to try again when the request fails", async () => {
    server.use(http.post("*/api/v1/alerts/unsubscribe", () => HttpResponse.error()));
    open("unsubscribe", MOCK_ALERT_TOKENS.valid);
    expect(await heading()).toBe("Something went wrong.");
  });

  it("always links back to the map", async () => {
    open("unsubscribe", MOCK_ALERT_TOKENS.valid);
    await heading();
    expect(screen.getByRole("link", { name: "Back to the map" }).getAttribute("href")).toBe("/");
  });
});
