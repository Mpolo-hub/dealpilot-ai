// Demo-readiness gap fixes (Stage 1, 2026-11-03): KPIs computed only from existing /v1 data.
import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { formatCount } from "../../src/domain/format";
import { formatMoneyCompact } from "../../src/domain/money";
import { text } from "../../src/text/en";
import { DIMENSIONS, installFakeApi, LINES } from "../fakeApi";
import { renderAt } from "../render";

const totalCents = LINES.reduce((s, l) => s + l[5], 0);
const totalUnits = LINES.reduce((s, l) => s + l[4], 0);
const orders = new Set(LINES.map((l) => l[0])).size;

describe("demo readiness", () => {
  it("Dashboard shows units sold and the average order value from the totals call", async () => {
    installFakeApi();
    renderAt("/");
    const ordersCard = await screen.findByRole("region", { name: text.dashboard.orders });
    await within(ordersCard).findByText(text.dashboard.unitsSold(formatCount(totalUnits)));
    const sales = await screen.findByRole("region", { name: text.dashboard.totalSales });
    const average = formatMoneyCompact(totalCents / 100 / orders);
    await within(sales).findByText(text.dashboard.averageOrder(average));
  });

  it("Products shows units sold per product and the best and lowest sellers", async () => {
    installFakeApi();
    renderAt("/products");
    const table = await screen.findByRole("table", { name: text.products.title });
    await within(table).findByRole("columnheader", { name: new RegExp(text.products.units) });
    const p003Units = LINES.filter((l) => l[3] === "P003").reduce((s, l) => s + l[4], 0);
    const p003Row = within(table).getAllByRole("row").find((r) => r.textContent?.includes("P003"))!;
    expect(p003Row.textContent).toContain(formatCount(p003Units));
    const best = DIMENSIONS.products.find((p) => p.product_id === "P003")!.name;
    const sold = new Set(LINES.map((l) => l[3]));
    const unsold = DIMENSIONS.products.filter((p) => !sold.has(p.product_id))
      .sort((a, b) => b.product_id.localeCompare(a.product_id))[0]!;
    const note = await screen.findByText(/^Best seller:/);
    expect(note.textContent).toContain(best);
    expect(note.textContent).toContain(`Lowest sales: ${unsold.name} ($0.00)`);
  });

  it("Data page states clearly that the data is synthetic", async () => {
    installFakeApi();
    renderAt("/data");
    const notice = await screen.findByRole("region", { name: text.data.syntheticTitle });
    expect(notice.textContent).toContain("seed 42");
    expect(notice.textContent).toContain("not real customer");
  });
});
