// API client (spec 007 section 12.3, FR-04, FR-06, FR-08, AC-UI-09).
import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ApiError, buildQuery, getJson, NetworkError } from "../../src/api/client";
import { metricsPath } from "../../src/api/endpoints";
import { errorMessage } from "../../src/api/errors";
import { useApi } from "../../src/hooks/useApi";
import { text } from "../../src/text/en";

describe("query strings", () => {
  it("repeats keys for lists and leaves out undefined values", () => {
    expect(buildQuery({ group_by: ["region", "product"], start: "2024-01-01", end: undefined }))
      .toBe("?group_by=region&group_by=product&start=2024-01-01");
    expect(buildQuery({})).toBe("");
  });

  it("never combines date buckets with other groups (AC-UI-09)", () => {
    expect(() => metricsPath({ group_by: ["date", "product"] })).toThrow();
    expect(() => metricsPath({ group_by: ["category", "date"] })).toThrow();
    expect(metricsPath({ start: "2024-01-01", end: "2024-01-31", group_by: ["date"], interval: "day" }))
      .toBe("/v1/sales/metrics?start=2024-01-01&end=2024-01-31&group_by=date&interval=day");
  });
});

describe("getJson", () => {
  it("only accepts same-origin paths", async () => {
    await expect(getJson("http://example.com/v1/metadata")).rejects.toThrow();
  });

  it("turns the spec 002 error body into ApiError", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(
      { error: { code: "result_too_large", message: "too many rows", details: [] } }),
    { status: 422 })));
    const error = await getJson("/v1/sales/metrics").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).code).toBe("result_too_large");
    expect(errorMessage(error).message).toBe(text.errors.resultTooLarge);
  });

  it("reports an unreachable API as NetworkError", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    await expect(getJson("/v1/metadata")).rejects.toBeInstanceOf(NetworkError);
    vi.stubGlobal("fetch", vi.fn(async () => new Response("proxy error", { status: 502 })));
    await expect(getJson("/v1/metadata")).rejects.toBeInstanceOf(NetworkError);
  });

  it("never shows the 503 message, which may name the data folder (FR-06)", () => {
    const shown = errorMessage(new ApiError(503, "data_unavailable", "D:\\secret\\folder missing"));
    expect(shown.message).toBe(text.errors.dataUnavailable);
    expect(shown.detail).toBeNull();
  });
});

describe("useApi (FR-08)", () => {
  it("cancels the older request when the path changes", async () => {
    const signals: AbortSignal[] = [];
    vi.stubGlobal("fetch", vi.fn((path: string, init: RequestInit) => {
      signals.push(init.signal!);
      return new Promise<Response>((resolve) => {
        setTimeout(() => resolve(Response.json({ path })), path.includes("slow") ? 50 : 1);
      });
    }));
    const { result, rerender } = renderHook(({ path }) => useApi<{ path: string }>(path),
      { initialProps: { path: "/v1/slow" } });
    rerender({ path: "/v1/fast" });
    await waitFor(() => expect(result.current[0].status).toBe("ready"));
    expect(signals[0]!.aborted).toBe(true);
    const state = result.current[0];
    expect(state.status === "ready" && state.data.path).toBe("/v1/fast");
  });
});
