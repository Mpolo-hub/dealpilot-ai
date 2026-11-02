// Page tests against the fake spec 002 API (spec 007 section 14). Expected values are
// computed here from the fixture lines, independently of the code under test.
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { text } from "../../src/text/en";
import { DIMENSIONS, errorResponse, installFakeApi, LINES, METADATA } from "../fakeApi";
import { currentLocation, renderAt } from "../render";

const sumCents = (filter: (l: (typeof LINES)[number]) => boolean = () => true) =>
  LINES.filter(filter).reduce((s, l) => s + l[5], 0);
const dollars = (cents: number) =>
  `$${Math.floor(cents / 100).toLocaleString("en-US")}.${String(cents % 100).padStart(2, "0")}`;

function card(name: string) {
  return screen.findByRole("region", { name });
}

function chartRows(title: string): string[][] {
  const table = screen.getByText(`${text.common.chartDescription}: ${title}`).closest("table")!;
  return [...table.querySelectorAll("tbody tr")].map((tr) =>
    [...tr.children].map((c) => c.textContent ?? ""));
}

function openDaysBetween(start: string, end: string): number {
  let count = 0;
  for (let t = Date.parse(`${start}T00:00:00Z`); t <= Date.parse(`${end}T00:00:00Z`); t += 86_400_000) {
    const md = new Date(t).toISOString().slice(5, 10);
    if (md !== "12-25" && md !== "01-01") count += 1;
  }
  return count;
}

describe("Dashboard (spec 007 section 5.1)", () => {
  it("AC-UI-01: totals equal the API totals, with the exact amount available", async () => {
    installFakeApi();
    renderAt("/");
    const sales = await card(text.dashboard.totalSales);
    await within(sales).findByText("$1.2M");
    expect(within(sales).getByText(new RegExp(dollars(sumCents()).replace(/[$.]/g, "\\$&"))))
      .toBeTruthy();
    const orders = await card(text.dashboard.orders);
    await within(orders).findByText(String(new Set(LINES.map((l) => l[0])).size));
  });

  it("AC-UI-02: active products on the range end; customers from row_counts", async () => {
    installFakeApi();
    renderAt("/");
    const products = await card(text.dashboard.products);
    // On 2024-12-31: P001, P003 and P004 are active; P002 stopped on 2024-03-01.
    expect(within(products).getByText("3")).toBeTruthy();
    expect(within(products).getByText(text.dashboard.activeNote("4", "Dec 31, 2024"))).toBeTruthy();
    expect(within(products).getByText(text.dashboard.active)).toBeTruthy();
    const customers = await card(text.dashboard.customers);
    await within(customers).findByText("2,000");
  });

  it("AC-UI-03: one point per day; missing days are zero", async () => {
    installFakeApi();
    renderAt("/");
    await card(text.dashboard.dailySales);
    await waitFor(() => expect(chartRows(text.dashboard.dailySales).length).toBe(731));
    const rows = chartRows(text.dashboard.dailySales);
    expect(rows.find((r) => r[0] === "Dec 25, 2023")?.[1]).toBe("$0");
    // $2,050.00 on Mar 10, 2023, shown in compact form ("$2K"; exact values are in tables).
    expect(rows.find((r) => r[0] === "Mar 10, 2023")?.[1]).toBe("$2K");
  });

  it("AC-UI-04: every region by name, regions without sales at 0%", async () => {
    installFakeApi();
    renderAt("/");
    const regions = await card(text.dashboard.salesByRegion);
    const legend = await within(regions).findByRole("list");
    for (const r of DIMENSIONS.regions) expect(within(legend).getByText(r.name)).toBeTruthy();
    const items = within(legend).getAllByRole("listitem").map((li) => li.textContent);
    expect(items).toContain("East0%");
    const share = Math.round((sumCents((l) => l[2] === "R01") / sumCents()) * 100);
    expect(items).toContain(`North${share}%`);
  });

  it("AC-UI-16 (D3): no badge on the default range; same period last year otherwise", async () => {
    installFakeApi();
    renderAt("/");
    const sales = await card(text.dashboard.totalSales);
    await within(sales).findByText("$1.2M");
    expect(within(sales).queryByText(/%/)).toBeNull();

    clearAndRender("/?start=2024-01-01&end=2024-12-31");
    const sales2024 = await card(text.dashboard.totalSales);
    const now = sumCents((l) => l[1].startsWith("2024"));
    const before = sumCents((l) => l[1].startsWith("2023"));
    const expected = `+${(((now - before) / before) * 100).toFixed(1)}%`;
    await within(sales2024).findByText(expected);
    const orders = await card(text.dashboard.orders);
    await within(orders).findByText("+100.0%"); // 4 orders in 2024, 2 in 2023
  });
});

function clearAndRender(url: string) {
  document.body.innerHTML = "";
  renderAt(url);
}

describe("Sales analysis (spec 007 section 5.2)", () => {
  it("AC-UI-05: top products by revenue, ties by ID, at most 10", async () => {
    installFakeApi();
    renderAt("/analysis");
    await card(text.analysis.topProducts);
    await waitFor(() => expect(chartRows(text.analysis.topProducts).length).toBe(3));
    expect(chartRows(text.analysis.topProducts).map((r) => r[0])).toEqual(["P003", "P001", "P002"]);
  });

  it("AC-UI-06: 12 monthly columns, zero months included, years from date_range", async () => {
    installFakeApi();
    renderAt("/analysis");
    await card(text.analysis.salesByMonth);
    await waitFor(() => expect(chartRows(text.analysis.salesByMonth).length).toBe(12));
    const rows = chartRows(text.analysis.salesByMonth);
    expect(rows[0]).toEqual(["Jan 2024", "$0"]);
    const select = screen.getByLabelText(text.analysis.year) as HTMLSelectElement;
    expect([...select.options].map((o) => o.value)).toEqual(["2023", "2024"]);
    fireEvent.change(select, { target: { value: "2023" } });
    await waitFor(() => expect(currentLocation).toContain("year=2023"));
    await waitFor(() => expect(chartRows(text.analysis.salesByMonth)[2]).toEqual(["Mar 2023", "$2K"]));
  });

  it("AC-UI-17 (D5): average revenue per open day, top product and top region", async () => {
    installFakeApi();
    renderAt("/analysis");
    const average = await card(text.analysis.averagePerDay);
    const expected = sumCents() / 100 / openDaysBetween("2023-01-01", "2024-12-31");
    expect(Math.round(expected)).toBe(1708); // 727 open days
    await within(average).findByText("$1.7K");
    const top = await card(text.analysis.topProduct);
    await within(top).findByText("P003");
    const region = await card(text.analysis.topRegion);
    await within(region).findByText("North");
    const growth = await card(text.analysis.growth);
    expect(within(growth).getByText(text.analysis.growthUnavailable)).toBeTruthy();
  });

  it("By product lists every product of the category filter, zero when unsold", async () => {
    installFakeApi();
    renderAt("/analysis?tab=products&category=Toys");
    const table = await screen.findByRole("table", { name: text.analysis.tabProducts });
    await waitFor(() => expect(within(table).getAllByRole("row").length).toBe(3));
    const rows = within(table).getAllByRole("row").slice(1).map((r) => r.textContent);
    expect(rows[0]).toContain("P003");
    expect(rows[1]).toContain("P004");
    expect(rows[1]).toContain("$0.00");
    expect(screen.getByText(text.analysis.ordersNote)).toBeTruthy();
  });

  it("By region lists every region, with exact revenue", async () => {
    installFakeApi();
    renderAt("/analysis?tab=regions");
    const table = await screen.findByRole("table", { name: text.analysis.tabRegions });
    await within(table).findByText(dollars(sumCents((l) => l[2] === "R01")));
    expect(within(table).getByText("East")).toBeTruthy();
  });
});

describe("Products (spec 007 section 5.3)", () => {
  it("AC-UI-07 and AC-UI-18 (D4): every product, status on the dataset end", async () => {
    installFakeApi();
    renderAt("/products");
    const table = await screen.findByRole("table", { name: text.products.title });
    await within(table).findByText(dollars(sumCents((l) => l[3] === "P001")));
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.length).toBe(4);
    const statuses = rows.map((r) => r.lastElementChild?.textContent);
    expect(statuses).toEqual(["Active", "Discontinued", "Active", "Active"]);
    expect(rows[3]!.textContent).toContain("$0.00");
  });

  it("search and filters narrow the list without a new request", async () => {
    const requested = installFakeApi();
    renderAt("/products");
    const table = await screen.findByRole("table", { name: text.products.title });
    await within(table).findByText("Kite Set");
    const before = requested.length;
    await userEvent.type(screen.getByRole("searchbox"), "kite");
    await waitFor(() => expect(within(table).getAllByRole("row").length).toBe(2));
    fireEvent.change(screen.getByLabelText(text.products.status), { target: { value: "discontinued" } });
    await screen.findByText(text.products.noMatch);
    expect(requested.length).toBe(before);
    expect(currentLocation).toContain("q=kite");
    expect(currentLocation).toContain("status=discontinued");
  });

  it("the result count follows the filters", async () => {
    installFakeApi();
    renderAt("/products");
    await screen.findByText(text.products.count("4", "4"));
    fireEvent.change(screen.getByLabelText(text.products.category), { target: { value: "Toys" } });
    await screen.findByText(text.products.count("2", "4"));
  });

  it("Categories tab: revenue and product count per category", async () => {
    installFakeApi();
    renderAt("/products?tab=categories");
    const table = await screen.findByRole("table", { name: text.products.tabCategories });
    await within(table).findByText(dollars(sumCents((l) => l[3] === "P003")));
    expect(within(table).getAllByRole("row").length).toBe(3);
  });
});

describe("Data (spec 007 section 5.4)", () => {
  it("AC-UI-08: every row count and the metadata fields, never parameters", async () => {
    const requested = installFakeApi();
    renderAt("/data");
    const table = await screen.findByRole("table", { name: text.data.tabOverview });
    const rows = within(table).getAllByRole("row").slice(1).map((r) => r.textContent);
    expect(rows.length).toBe(Object.keys(METADATA.row_counts).length);
    expect(rows[0]).toBe("Regions3");
    expect(rows).toContain("Customers2,000");
    clearAndRender("/data?tab=metadata");
    const meta = await screen.findByRole("table", { name: text.data.tabMetadata });
    await within(meta).findByText("python 3.13.17, numpy 2.5.4, pyarrow 26.0.0");
    const rowsByField = Object.fromEntries(within(meta).getAllByRole("row").slice(1)
      .map((r) => [r.firstElementChild?.textContent, r.lastElementChild?.textContent]));
    expect(rowsByField[text.data.seed]).toBe("42");
    expect(rowsByField[text.data.generatorVersion]).toBe("0.1.0");
    await waitFor(() => expect(within(meta).getAllByRole("row").at(-1)?.lastElementChild?.textContent)
      .toBe("0.1.0")); // API version from /health
    const seedCard = await card(text.data.seed);
    expect(within(seedCard).getByText("42")).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/parameters|base_demand/);
    expect(requested.every((r) => !r.includes("parameters"))).toBe(true);
  });
});

describe("Data summary cards", () => {
  it("show seed, period length, table count and API version from the API", async () => {
    installFakeApi();
    renderAt("/data");
    const period = await card(text.data.periodCard);
    // 2023-01-01 to 2024-12-31: 365 + 366 days.
    expect(within(period).getByText(text.data.periodDays("731"))).toBeTruthy();
    const tables = await card(text.data.tablesCard);
    expect(within(tables).getByText(String(Object.keys(METADATA.row_counts).length))).toBeTruthy();
    const api = await card(text.data.apiVersion);
    await within(api).findByText("0.1.0");
  });
});

describe("errors and states", () => {
  it("AC-UI-09: a result_too_large answer only breaks its own card", async () => {
    installFakeApi((url) => url.searchParams.get("group_by") === "region"
      ? errorResponse(422, "result_too_large", "too many groups") : undefined);
    renderAt("/");
    const regions = await card(text.dashboard.salesByRegion);
    await within(regions).findByText(text.errors.resultTooLarge);
    const sales = await card(text.dashboard.totalSales);
    await within(sales).findByText("$1.2M");
  });

  it("AC-UI-10: 503 shows Data unavailable without any path", async () => {
    installFakeApi((url) => url.pathname === "/v1/dimensions"
      ? errorResponse(503, "data_unavailable", "D:\\DealPilot AI\\data\\raw is missing") : undefined);
    renderAt("/");
    await screen.findByRole("heading", { name: text.errors.dataUnavailableTitle });
    expect(document.body.textContent).not.toContain("DealPilot AI\\data");
  });

  it("AC-UI-10: an unreachable API shows the start command", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    renderAt("/data");
    await screen.findByText(text.errors.network);
    expect(screen.getByText(text.errors.networkHelp)).toBeTruthy();
  });

  it("an empty period shows the empty state", async () => {
    installFakeApi();
    renderAt("/?start=2023-01-01&end=2023-01-31");
    const daily = await card(text.dashboard.dailySales);
    await within(daily).findByText(text.common.noSales);
  });
});

const FRENCH = ["Tableau de bord", "Données", "Prévisions", "Produits", "Régions", "Clients",
  "Rapports", "Paramètres", "Rechercher", "Ventes", "Commandes", "Actifs", "Générer",
  "Vue d'ensemble", "Métadonnées", "Catégorie", "Statut", "Toutes", "Nom du produit", "Prix",
  "Croissance", "Meilleur", "Bienvenue", "Mot de passe", "Se connecter", "Analyse des"];
const PAGES = ["/", "/analysis", "/analysis?tab=products", "/analysis?tab=regions", "/products",
  "/products?tab=categories", "/data", "/data?tab=metadata", "/nowhere"];

describe("product rules across pages", () => {
  it("AC-UI-11: every string is English", async () => {
    const strings = JSON.stringify(text);
    for (const word of FRENCH) expect(strings).not.toContain(word);
    installFakeApi();
    for (const page of PAGES) {
      clearAndRender(page);
      await screen.findAllByRole("heading", { level: 1 });
      await waitFor(() => expect(screen.queryAllByRole("status").length).toBe(0));
      for (const word of FRENCH) expect(document.body.textContent).not.toContain(word);
    }
  });

  it("AC-UI-09 and AC-UI-12: same-origin requests only; dates never grouped with products", async () => {
    const requested = installFakeApi();
    for (const page of PAGES) {
      clearAndRender(page);
      await waitFor(() => expect(screen.queryAllByRole("status").length).toBe(0));
    }
    // Answers are cached for the page load, so each distinct path is requested once.
    expect(new Set(requested).size).toBe(requested.length);
    expect(requested.some((r) => r.includes("group_by=date"))).toBe(true);
    for (const path of requested) {
      expect(path.startsWith("/v1/") || path === "/health").toBe(true);
      const params = new URL(path, "http://x").searchParams.getAll("group_by");
      if (params.includes("date")) expect(params).toEqual(["date"]);
    }
  });

  it("AC-UI-15: no out-of-scope control is rendered", async () => {
    installFakeApi();
    for (const page of PAGES) {
      clearAndRender(page);
      await waitFor(() => expect(screen.queryAllByRole("status").length).toBe(0));
      const nav = screen.getByRole("navigation", { name: text.app.mainNavigation });
      expect(within(nav).getAllByRole("link").map((a) => a.textContent))
        .toEqual(["Dashboard", "Data", "Analysis", "Products"]);
      const controls = [...screen.queryAllByRole("button"), ...screen.queryAllByRole("link")]
        .map((e) => e.textContent ?? "");
      for (const label of controls) {
        expect(label).not.toMatch(/\b(new|generate|sign in|log in|export|notifications?)\b/i);
      }
      expect(document.body.textContent).not.toMatch(/By customer|Promotion effects|Price/);
      // The Data page may show the expected_demand row count (spec 007 section 5.4), never
      // its contents; elsewhere "Expected demand" must not appear (spec 002 section 3.8).
      if (!page.startsWith("/data")) expect(document.body.textContent).not.toContain("Expected demand");
      if (!page.startsWith("/products")) expect(screen.queryByRole("searchbox")).toBeNull();
    }
  });
});

describe("URL state (FR-07, D7)", () => {
  it("ignores invalid or out-of-range dates and uses the dataset range", async () => {
    const requested = installFakeApi();
    renderAt("/?start=2020-01-01&end=2024-01-01");
    await card(text.dashboard.totalSales);
    await waitFor(() => expect(requested.some((r) => r.includes("start=2023-01-01&end=2024-12-31")))
      .toBe(true));
    expect(requested.some((r) => r.includes("2020-01-01"))).toBe(false);
  });

  it("validates the range before any request and writes it to the URL", async () => {
    installFakeApi();
    renderAt("/");
    const form = await screen.findByRole("form", { name: text.common.dateRange });
    const [from, to] = within(form).getAllByDisplayValue(/\d{4}-\d{2}-\d{2}/) as HTMLInputElement[];
    fireEvent.change(from!, { target: { value: "2024-06-01" } });
    fireEvent.change(to!, { target: { value: "2024-05-01" } });
    expect(within(form).getByRole("alert").textContent).toBe(text.validation.startAfterEnd);
    expect((within(form).getByRole("button", { name: text.common.apply }) as HTMLButtonElement).disabled)
      .toBe(true);
    fireEvent.change(to!, { target: { value: "2024-06-30" } });
    fireEvent.click(within(form).getByRole("button", { name: text.common.apply }));
    await waitFor(() => expect(currentLocation).toBe("/?start=2024-06-01&end=2024-06-30"));
    expect(localStorage.length).toBe(0);
  });

  it("the tab is part of the URL", async () => {
    installFakeApi();
    renderAt("/analysis?tab=regions");
    const tabs = await screen.findByRole("navigation", { name: text.analysis.title });
    expect(within(tabs).getByRole("link", { current: "page" }).textContent).toBe(text.analysis.tabRegions);
  });

  it("an unknown URL shows Page not found", async () => {
    installFakeApi();
    renderAt("/forecasts");
    await screen.findByRole("heading", { name: text.notFound.title });
  });
});
