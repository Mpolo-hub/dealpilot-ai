// Prediction page (spec 007 D14 amendment, 2026-11-04) against the fake API. Expected values
// are worked out here from the fixture lines (tests/fakeApi.ts) and spec 003 section 6.1.
// @ts-expect-error Node types are not installed; Vitest runs the tests in Node.
import { readFileSync } from "node:fs";

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import evaluation from "../../src/evaluation/exploratory-backtest.json";
import { change, forecastKpis, forecastRows, unitsByDate, windowSum } from "../../src/domain/forecast";
import { text } from "../../src/text/en";
import { errorResponse, installFakeApi } from "../fakeApi";
import { currentLocation, renderAt } from "../render";

const t = text.prediction;

async function generate() {
  await userEvent.click(await screen.findByRole("button", { name: t.generate }));
}

function tableRows(): string[][] {
  const table = screen.getByRole("table", { name: new RegExp(`^${t.tabTable}`) });
  return [...table.querySelectorAll("tbody tr")].map((tr) =>
    [...tr.children].map((c) => c.textContent ?? ""));
}

function forecastCalls(requested: string[]): string[] {
  return requested.filter((p) => p.startsWith("/v1/forecasts"));
}

describe("Prediction page", () => {
  it("is in the menu at /prediction and starts with an empty state, without a forecast request", async () => {
    const requested = installFakeApi();
    renderAt("/prediction");
    expect(await screen.findByRole("heading", { name: t.title, level: 1 })).toBeTruthy();
    const nav = screen.getByRole("navigation", { name: text.app.mainNavigation });
    expect(within(nav).getByRole("link", { name: t.title }).getAttribute("href")).toBe("/prediction");
    expect(await screen.findByText(t.start)).toBeTruthy();
    expect(forecastCalls(requested)).toEqual([]);
  });

  it("Generate Forecast calls the real API path and shows the KPIs, chart, details and table", async () => {
    const requested = installFakeApi();
    renderAt("/prediction");
    await generate();
    // Default settings: total level, cutoff = dataset end, 28 days.
    await screen.findByRole("region", { name: t.forecasted });
    expect(forecastCalls(requested)).toEqual(["/v1/forecasts?level=total&cutoff=2024-12-31&horizon=28"]);
    expect(currentLocation).toBe("/prediction?level=total&cutoff=2024-12-31&horizon=28");
    // Fixture: the only sale in Dec 25 to Dec 31 is 1 unit on Dec 30, so each weekly
    // repeat forecasts 1 unit on the 6th day: 4 units over 28 days.
    const historical = screen.getByRole("region", { name: t.historical });
    expect(within(historical).getByText("1")).toBeTruthy();
    // Nov 6 to Dec 3 had no sales, so there is no percent change for history.
    expect(within(historical).queryByText(/%/)).toBeNull();
    const forecasted = screen.getByRole("region", { name: t.forecasted });
    expect(within(forecasted).getByText("4")).toBeTruthy();
    expect(within(forecasted).getByText("+300.0%")).toBeTruthy(); // 4 vs 1 over the last 28 days
    const horizon = screen.getByRole("region", { name: t.horizonCard });
    expect(within(horizon).getByText("28 days")).toBeTruthy();
    expect(within(horizon).getByText("Jan 1, 2025 to Jan 28, 2025")).toBeTruthy();
    expect(within(screen.getByRole("region", { name: t.model })).getByText("Seasonal Naive v1.0")).toBeTruthy();
    const details = screen.getByRole("region", { name: t.details });
    expect(within(details).getByText("Jan 1, 2023 to Dec 31, 2024")).toBeTruthy();
    expect(within(details).getByText(t.note)).toBeTruthy();
    // Chart: actual and forecast lines, a cutoff marker, no band.
    expect(document.querySelector("[data-testid=actual-line]")?.getAttribute("d")).toMatch(/^M/);
    expect(document.querySelector("[data-testid=forecast-line]")?.getAttribute("d")).toMatch(/^M/);
    expect(document.querySelector("[data-testid=cutoff-marker]")).toBeTruthy();
    expect(screen.getByText(t.cutoffMarker("Dec 31, 2024"))).toBeTruthy();
    expect(document.querySelectorAll("figure path")).toHaveLength(2);
    // Table: 28 rows after the dataset end, so no actual exists anywhere.
    const rows = tableRows();
    expect(rows).toHaveLength(28);
    expect(rows[5]).toEqual(["Jan 6, 2025", "Mon", "—", "1", "—", "—", "—"]);
    expect(rows.every((r) => r[2] === "—")).toBe(true);
  });

  it("product and region level with a past cutoff shows actuals, errors and APE", async () => {
    const requested = installFakeApi();
    renderAt("/prediction");
    await userEvent.selectOptions(await screen.findByLabelText(t.level), "product_region");
    await userEvent.selectOptions(screen.getByLabelText(t.category), "Toys");
    // The category narrows the product list.
    const products = within(screen.getByLabelText(t.product)).getAllByRole("option").map((o) => o.textContent);
    expect(products).toEqual(["Kite Set (P003)", "Puzzle Box (P004)"]);
    await userEvent.selectOptions(screen.getByLabelText(t.product), "P003");
    // Every select carries its full selected text as a tooltip.
    expect(screen.getByLabelText(t.level).getAttribute("title")).toBe(t.levels.product_region);
    expect(screen.getByLabelText(t.product).getAttribute("title")).toBe("Kite Set (P003)");
    await userEvent.selectOptions(screen.getByLabelText(t.region), "R01");
    const cutoff = screen.getByLabelText(t.cutoff);
    await userEvent.clear(cutoff);
    await userEvent.type(cutoff, "2024-07-14");
    await userEvent.selectOptions(screen.getByLabelText(t.horizon), "7");
    await generate();
    await screen.findByRole("region", { name: t.forecasted });
    expect(forecastCalls(requested)).toEqual([
      "/v1/forecasts?level=product_region&product_id=P003&region_id=R01&cutoff=2024-07-14&horizon=7"]);
    // Fixture: P003 in R01 sold 5 units on Jul 20 and nothing in the week before the cutoff.
    const rows = tableRows();
    expect(rows).toHaveLength(7);
    expect(rows[5]).toEqual(["Jul 20, 2024", "Sat", "5", "0", "-5", "5", "100.0%"]);
    expect(rows[0]).toEqual(["Jul 15, 2024", "Mon", "0", "0", "0", "0", text.common.notAvailable]);
    expect(screen.getByText(t.chartSubtitle("Kite Set (P003), North"))).toBeTruthy();
  });

  it("tells when the product launched after the cutoff", async () => {
    installFakeApi();
    renderAt("/prediction?level=product_region&product_id=P003&region_id=R01&cutoff=2024-03-31&horizon=7");
    expect(await screen.findByText(t.notLaunched("Jun 1, 2024"))).toBeTruthy();
  });

  it("disables the button while loading, so a second click sends nothing", async () => {
    let release: (r: Response) => void = () => undefined;
    const requested = installFakeApi((url) => (url.pathname === "/v1/forecasts"
      ? new Promise<Response>((resolve) => { release = resolve; }) : undefined));
    renderAt("/prediction");
    await generate();
    const busy = await screen.findByRole("button", { name: t.generating });
    expect(busy).toHaveProperty("disabled", true);
    await userEvent.click(busy);
    expect(forecastCalls(requested)).toHaveLength(1);
    release(Response.json({
      level: "total", key: {}, cutoff: "2024-12-31", horizon: 28,
      model: { name: "seasonal_naive", version: "1.0", settings: {} }, uses_planned_promotions: false,
      points: [{ date: "2025-01-01", forecast: 3, lower_80: null, upper_80: null }],
    }));
    expect(await screen.findByRole("button", { name: t.generate })).toHaveProperty("disabled", false);
  });

  it("an API error shows the error state with a retry", async () => {
    installFakeApi((url) => (url.pathname === "/v1/forecasts"
      ? errorResponse(422, "invalid_filter", "A key value doesn't exist in the data.") : undefined));
    renderAt("/prediction");
    await generate();
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain(text.errors.filter);
    expect(within(alert).getByRole("button", { name: text.common.tryAgain })).toBeTruthy();
  });

  it("data unavailable shows the data-unavailable view", async () => {
    installFakeApi((url) => (url.pathname === "/v1/forecasts"
      ? errorResponse(503, "data_unavailable") : undefined));
    renderAt("/prediction?level=total&cutoff=2024-12-31&horizon=28");
    expect(await screen.findByRole("heading", { name: text.errors.dataUnavailableTitle })).toBeTruthy();
  });

  it("refuses a cutoff outside the allowed range without calling the API", async () => {
    const requested = installFakeApi();
    renderAt("/prediction");
    const cutoff = await screen.findByLabelText(t.cutoff);
    await userEvent.clear(cutoff);
    await userEvent.type(cutoff, "2023-01-03"); // before start + 6
    await generate();
    expect((await screen.findByRole("alert")).textContent).toBe(
      t.cutoffInvalid("Jan 7, 2023", "Dec 31, 2024"));
    expect(forecastCalls(requested)).toEqual([]);
  });

  it("Model Evaluation shows the exploratory backtest, labelled, with the harness numbers", async () => {
    installFakeApi();
    renderAt("/prediction?level=category&category=Home&cutoff=2024-12-31&horizon=28&tab=evaluation");
    const table = await screen.findByRole("table", { name: evaluation.label });
    expect(screen.getAllByText("Exploratory backtest, not a formal evaluation").length).toBeGreaterThan(0);
    const rows = [...table.querySelectorAll("tbody tr")].map((tr) =>
      [...tr.children].map((c) => c.textContent ?? ""));
    expect(rows).toHaveLength(6);
    const total = evaluation.metrics.find((m) => m.model === "seasonal_naive" && m.level === "total")!;
    expect(rows[0]).toEqual(["Total", "Seasonal Naive", `${(total.wape * 100).toFixed(1)}%`,
      total.mae.toFixed(2), `${(total.bias * 100).toFixed(2)}%`, total.mase_mean.toFixed(2), "Reference"]);
    const naive = evaluation.metrics.find((m) => m.model === "naive" && m.level === "total")!;
    expect(rows[1]?.[6]).toBe(naive.relmae!.toFixed(2));
    expect(rows[2]?.[0]).toContain(t.selectedLevel); // the category level is highlighted
    expect(evaluation.run_class).toBe("exploratory");
    expect(evaluation.decision_grade).toBe(false);
    expect(document.body.textContent).toContain(t.evaluationLimits);
  });

  it("shows no control without a real function", async () => {
    installFakeApi();
    renderAt("/prediction?level=total&cutoff=2024-12-31&horizon=28");
    await screen.findByRole("region", { name: t.forecasted });
    const labels = [...screen.queryAllByRole("button"), ...screen.queryAllByRole("link")]
      .map((e) => e.textContent ?? "");
    for (const label of labels) {
      expect(label).not.toMatch(/\b(settings|notifications?|export|new|sign in|log in)\b/i);
    }
    expect(document.body.textContent).not.toMatch(/John Doe|Administrator|Expected demand|confidence/i);
  });

  it("the Model card value may wrap and changes sit under the values (no overflow)", async () => {
    // jsdom has no layout: this checks the classes and rules that keep the text inside the
    // card. The widths 1600, 1280, 1024 and 375 px were measured in a real browser.
    installFakeApi();
    renderAt("/prediction?level=total&cutoff=2024-12-31&horizon=28");
    const model = await screen.findByRole("region", { name: t.model });
    const value = within(model).getByText("Seasonal Naive v1.0");
    expect(value.className).toMatch(/kpiValueText/);
    const uiCss: string = readFileSync("src/components/ui.module.css", "utf-8");
    const start = uiCss.indexOf(".kpiValueText {");
    const rule = uiCss.slice(start, uiCss.indexOf("}", start));
    expect(start).toBeGreaterThan(-1);
    expect(rule).toContain("white-space: normal");
    expect(rule).toContain("overflow-wrap: anywhere");
    // The change badge is part of the note line, not beside the label.
    const forecasted = screen.getByRole("region", { name: t.forecasted });
    const badge = within(forecasted).getByText("+300.0%");
    expect(badge.closest("p")?.textContent).toContain(t.forecastedNote(28));
    expect(within(forecasted).getByText(t.vsLast(28), { selector: "span[aria-hidden]" })).toBeTruthy();
  });

  it("the Data page period value may wrap like the Model card", async () => {
    installFakeApi();
    renderAt("/data");
    const period = await screen.findByRole("region", { name: text.data.periodCard });
    expect(within(period).getByText(text.data.periodDays("731")).className).toMatch(/kpiValueText/);
  });

  it("in public mode it is protected like the other pages", async () => {
    vi.stubEnv("VITE_DEMO_MODE", "public");
    installFakeApi((url) => (url.pathname.startsWith("/v1/") ? errorResponse(401, "unauthorized") : undefined));
    renderAt("/prediction");
    await screen.findByRole("heading", { name: text.welcome.title, level: 1 });
    await waitFor(() => expect(currentLocation).toBe("/welcome"));
    vi.unstubAllEnvs();
  });
});

describe("Prediction rules (domain/forecast)", () => {
  const units = unitsByDate([{ date: "2024-01-02", units: 4 }, { date: "2024-01-03", units: 6 }]);

  it("rows: em dash cases are null; APE needs a positive actual", () => {
    const rows = forecastRows([
      { date: "2024-01-02", forecast: 5, lower_80: null, upper_80: null },
      { date: "2024-01-04", forecast: 2, lower_80: null, upper_80: null },
      { date: "2024-01-05", forecast: 2, lower_80: null, upper_80: null },
    ], units, "2024-01-04");
    expect(rows[0]).toEqual({ date: "2024-01-02", actual: 4, forecast: 5, difference: 1, absError: 1, ape: 0.25 });
    expect(rows[1]).toEqual({ date: "2024-01-04", actual: 0, forecast: 2, difference: 2, absError: 2, ape: null });
    expect(rows[2]).toEqual({ date: "2024-01-05", actual: null, forecast: 2, difference: null, absError: null, ape: null });
  });

  it("sums and changes: no change without a full, positive comparison window", () => {
    expect(windowSum(units, "2024-01-01", "2024-01-03", "2024-01-01")).toBe(10);
    expect(windowSum(units, "2023-12-31", "2024-01-03", "2024-01-01")).toBeNull();
    expect(change(12, 10)).toBeCloseTo(0.2);
    expect(change(5, 0)).toBeNull();
    const kpis = forecastKpis([{ date: "2024-01-04", forecast: 7, lower_80: null, upper_80: null }],
      units, "2024-01-03", "2024-01-01");
    expect(kpis).toEqual({ historyFirst: "2024-01-01", historyDays: 3, historical: 10,
      historicalChange: null, forecasted: 7, forecastChange: change(7, 6) });
  });
});
