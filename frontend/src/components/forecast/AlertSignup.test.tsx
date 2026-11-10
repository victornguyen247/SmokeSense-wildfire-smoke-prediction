import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { PointQuery } from "../../api/forecast";
import { server } from "../../test/setup";
import { AlertSignup } from "./AlertSignup";

const SUBSCRIPTIONS = "*/api/v1/alerts/subscriptions";

async function signUp(email: string, query: PointQuery = { zip: "95926" }) {
  const user = userEvent.setup();
  render(<AlertSignup query={query} label="ZIP 95926" />);
  if (email) await user.type(screen.getByRole("textbox", { name: "Email address" }), email);
  await user.click(screen.getByRole("button", { name: "Sign up" }));
}

describe("AlertSignup", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
  });

  it("names the location and shows the privacy note and experimental line next to the button", () => {
    render(<AlertSignup query={{ zip: "95926" }} label="ZIP 95926" />);
    expect(screen.getByText("Alerts for ZIP 95926.")).toBeTruthy();
    expect(screen.getByText(/experimental model estimate, not an official warning/)).toBeTruthy();
    expect(screen.getByText(/all subscriber data is deleted by December 11, 2026/)).toBeTruthy();
  });

  it("sends the email and the card's location, then asks to check email", async () => {
    let sent: unknown;
    server.use(
      http.post(SUBSCRIPTIONS, async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json({ status: "pending_confirmation" }, { status: 202 });
      }),
    );
    const log = vi.spyOn(console, "log");
    await signUp("Person@Example.com", { lat: 39.73, lon: -121.84 });

    const done = await screen.findByRole("status");
    expect(done.textContent).toContain("Check your email");
    expect(done.textContent).toContain("Person@Example.com");
    expect(done.textContent).toContain("48 hours");
    expect(sent).toEqual({ email: "Person@Example.com", lat: 39.73, lon: -121.84 });
    // The address is never stored or logged.
    expect(localStorage.length).toBe(0);
    expect(log).not.toHaveBeenCalled();
  });

  it("checks the address before sending anything", async () => {
    const request = vi.fn();
    server.use(http.post(SUBSCRIPTIONS, () => request()));
    await signUp("not-an-email");
    expect(screen.getByRole("alert").textContent).toContain("Enter an email address");
    expect(screen.getByRole("textbox", { name: "Email address" }).getAttribute("aria-invalid")).toBe("true");
    expect(request).not.toHaveBeenCalled();
  });

  it("asks for an address when the field is empty", async () => {
    await signUp("");
    expect(screen.getByRole("alert").textContent).toContain("Enter an email address");
  });

  it("shows the field error for the API's invalid_query", async () => {
    server.use(
      http.post(SUBSCRIPTIONS, () =>
        HttpResponse.json({ code: "invalid_query", message: "email: bad" }, { status: 400 }),
      ),
    );
    await signUp("a@b.co");
    expect((await screen.findByRole("alert")).textContent).toBe("Check the email address.");
  });

  it("says California only for a location outside it", async () => {
    await signUp("a@b.co", { lat: 45.5, lon: -122.6 });
    expect((await screen.findByRole("alert")).textContent).toBe("SmokeSense only covers California.");
  });

  it("says the ZIP wasn't found", async () => {
    await signUp("a@b.co", { zip: "10001" });
    expect((await screen.findByRole("alert")).textContent).toBe("We couldn't find that ZIP code.");
  });

  it("asks to try again on a server error", async () => {
    server.use(
      http.post(SUBSCRIPTIONS, () =>
        HttpResponse.json({ code: "internal_error", message: "x" }, { status: 500 }),
      ),
    );
    await signUp("a@b.co");
    expect((await screen.findByRole("alert")).textContent).toBe("Something went wrong. Please try again.");
  });

  it("asks to try again when the network fails", async () => {
    server.use(http.post(SUBSCRIPTIONS, () => HttpResponse.error()));
    await signUp("a@b.co");
    expect((await screen.findByRole("alert")).textContent).toBe("Something went wrong. Please try again.");
  });
});
