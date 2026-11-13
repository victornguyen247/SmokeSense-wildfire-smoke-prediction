import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { PointForecast } from "../../api/models";
import { forecastPoint, forecastPointNoForecast, meta } from "../../mocks/fixtures";
import { PointForecastCard } from "./PointForecastCard";
import { AlertWarning } from "./AlertWarning";

const success = (data: PointForecast) => ({ status: "success" as const, data, retry: () => {} });

describe("AlertWarning", () => {
  it("shows the open episode with its peak and the experimental line", () => {
    render(<AlertWarning alert={forecastPoint.cell.active_alert} categories={meta.aqi_categories} />);
    const warning = screen.getByRole("status");
    expect(warning.textContent).toContain("Model expects smoke unhealthy for sensitive groups.");
    expect(warning.textContent).toContain("105.1 µg/m³");
    expect(warning.textContent).toContain("Experimental model estimate, not an official warning.");
    // The category color comes from /meta.
    expect(warning.style.borderLeftColor).not.toBe("");
  });

  it("shows nothing when there is no open episode", () => {
    const { container } = render(<AlertWarning alert={null} categories={meta.aqi_categories} />);
    expect(container.innerHTML).toBe("");
  });

  it("shows nothing when the API leaves the field out", () => {
    const { container } = render(<AlertWarning alert={undefined} categories={meta.aqi_categories} />);
    expect(container.innerHTML).toBe("");
  });
});

describe("PointForecastCard alerts", () => {
  const card = (data: PointForecast) => (
    <PointForecastCard
      label="ZIP 95926"
      query={{ zip: "95926" }}
      forecast={success(data)}
      meta={meta}
      horizon={1}
      onClose={() => {}}
    />
  );

  it("shows the warning and the sign-up form for a location with an open episode", () => {
    render(card(forecastPoint));
    expect(screen.getByText("Model expects smoke unhealthy for sensitive groups.")).toBeTruthy();
    expect(screen.getByRole("textbox", { name: "Email address" })).toBeTruthy();
  });

  it("drops the warning when no horizon reaches its cut-off", () => {
    render(card(forecastPointNoForecast));
    expect(screen.queryByText(/Model expects smoke/)).toBeNull();
    // The sign-up form is still offered.
    expect(screen.getByRole("textbox", { name: "Email address" })).toBeTruthy();
  });
});
