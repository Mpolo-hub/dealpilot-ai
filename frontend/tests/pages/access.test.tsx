// Stage 1 public demo screens (spec 014 JA-FR-05 and JA-FR-08, spec 007 amendment A7-H1,
// acceptance criteria AC-S1-UI-01 to 06). The public mode is set with vi.stubEnv.
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { text } from "../../src/text/en";
import { errorResponse, installFakeApi } from "../fakeApi";
import { currentLocation, renderAt } from "../render";

function publicMode() {
  vi.stubEnv("VITE_DEMO_MODE", "public");
}

/** Put a fragment token in the browser address, as the invitation link does. */
function openLink(hash: string) {
  window.history.replaceState(null, "", `/access${hash}`);
}

function fetchCalls(): [string, RequestInit | undefined][] {
  return vi.mocked(fetch).mock.calls as unknown as [string, RequestInit | undefined][];
}

afterEach(() => {
  window.history.replaceState(null, "", "/");
});

describe("access page S1-a (JA-FR-05)", () => {
  it("AC-S1-UI-01: a valid link redeems the token, removes the hash and opens the Dashboard", async () => {
    publicMode();
    openLink("#good-token");
    installFakeApi((url) => url.pathname === "/access/redeem" ? new Response(null, { status: 204 }) : undefined);
    renderAt("/access");
    await screen.findByRole("heading", { name: text.dashboard.title, level: 1 });
    expect(currentLocation).toBe("/dashboard");
    expect(window.location.hash).toBe("");
    const [path, init] = fetchCalls().find(([p]) => p === "/access/redeem")!;
    expect(path).toBe("/access/redeem");
    expect(init?.method).toBe("POST");
    expect(init?.credentials).toBe("same-origin");
    expect((init?.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
    expect(JSON.parse(String(init?.body))).toEqual({ token: "good-token" });
  });

  it("AC-S1-UI-01: shows the opening message while the redemption is pending", async () => {
    publicMode();
    openLink("#slow-token");
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(() => undefined)));
    renderAt("/access");
    expect(await screen.findByText(text.access.opening)).toBeTruthy();
    expect(window.location.hash).toBe("");
  });

  it("AC-S1-UI-01: an invalid link shows only the generic message and removes the hash", async () => {
    publicMode();
    openLink("#bad-token");
    installFakeApi((url) => url.pathname === "/access/redeem"
      ? errorResponse(401, "invalid_link", "This link is not valid or has expired.") : undefined);
    renderAt("/access");
    await screen.findByText(text.access.invalidLink);
    expect(window.location.hash).toBe("");
    expect(currentLocation).toBe("/access");
    expect(screen.queryByRole("navigation", { name: text.app.mainNavigation })).toBeNull();
  });

  it("AC-S1-UI-01: every other failure shows the same generic message", async () => {
    for (const [status, code] of [[403, "forbidden"], [503, "service_unavailable"]] as const) {
      publicMode();
      openLink("#token");
      installFakeApi((url) => url.pathname === "/access/redeem" ? errorResponse(status, code) : undefined);
      const view = renderAt("/access");
      await screen.findByText(text.access.invalidLink);
      view.unmount();
    }
    publicMode();
    openLink("#token");
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    renderAt("/access");
    await screen.findByText(text.access.invalidLink);
  });

  it("AC-S1-UI-01: no token shows the generic message without any request", async () => {
    publicMode();
    openLink("");
    const requested = installFakeApi();
    renderAt("/access");
    await screen.findByText(text.access.invalidLink);
    expect(requested).toEqual([]);
  });

  it("AC-S1-UI-01: a 429 on redemption shows the rate-limit message", async () => {
    publicMode();
    openLink("#token");
    installFakeApi((url) => url.pathname === "/access/redeem" ? errorResponse(429, "rate_limited") : undefined);
    renderAt("/access");
    await screen.findByText(text.errors.rateLimited);
    expect(screen.queryByText(text.access.invalidLink)).toBeNull();
  });
});

describe("expired session and sign-out (S1-b and S1-c, amended by spec 014 Annex D)", () => {
  it("AC-S1-UI-02 (amended): a 401 from a /v1 call after sign-in goes to /login with a message", async () => {
    publicMode();
    let calls = 0;
    installFakeApi((url) => {
      if (url.pathname !== "/v1/metadata") return undefined;
      calls += 1;
      return calls === 1 ? undefined : errorResponse(401, "unauthorized"); // probe ok, then expired
    });
    renderAt("/data");
    await screen.findByText(text.access.signedOut);
    await waitFor(() => expect(currentLocation).toBe("/login"));
    expect(screen.getByRole("heading", { name: text.login.title, level: 1 })).toBeTruthy();
    expect(screen.queryByRole("navigation", { name: text.app.mainNavigation })).toBeNull();
  });

  it("AC-S1-UI-03 (amended): sign-out calls /access/logout, then goes to /welcome", async () => {
    publicMode();
    installFakeApi((url) => url.pathname === "/access/logout" ? new Response(null, { status: 204 }) : undefined);
    renderAt("/dashboard");
    await screen.findByRole("heading", { name: text.dashboard.title, level: 1 });
    await userEvent.click(screen.getByRole("button", { name: text.access.signOut }));
    await screen.findByRole("heading", { name: text.welcome.title, level: 1 });
    expect(currentLocation).toBe("/welcome");
    const [, init] = fetchCalls().find(([p]) => p === "/access/logout")!;
    expect(init?.method).toBe("POST");
    expect(init?.credentials).toBe("same-origin");
    expect((init?.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
    expect(JSON.parse(String(init?.body))).toEqual({});
  });
});

describe("demo notice S1-d and local mode", () => {
  it("AC-S1-UI-04: the demo notice is on every public page", async () => {
    publicMode();
    installFakeApi();
    for (const page of ["/", "/analysis", "/products", "/data", "/nowhere"]) {
      const view = renderAt(page);
      await screen.findAllByRole("heading", { level: 1 });
      expect(screen.getByText(text.access.demoNotice)).toBeTruthy();
      view.unmount();
    }
    openLink("");
    renderAt("/access");
    await screen.findByText(text.access.invalidLink);
    expect(screen.getByText(text.access.demoNotice)).toBeTruthy();
  });

  it("AC-S1-UI-04: local mode has no demo notice, no sign-out button and no access route", async () => {
    installFakeApi((url) => url.pathname === "/v1/metadata" ? errorResponse(401, "unauthorized") : undefined);
    renderAt("/");
    await screen.findByRole("heading", { name: text.dashboard.title, level: 1 });
    expect(screen.queryByText(text.access.demoNotice)).toBeNull();
    expect(screen.queryByRole("button", { name: text.access.signOut })).toBeNull();
    // A 401 never switches the local app to the signed-out page.
    await waitFor(() => expect(screen.queryAllByRole("status").length).toBe(0));
    expect(screen.queryByText(text.access.signedOut)).toBeNull();
  });

  it("AC-S1-UI-04: in local mode /access is the Page not found screen, as before", async () => {
    installFakeApi();
    renderAt("/access");
    await screen.findByRole("heading", { name: text.notFound.title });
  });
});

describe("rate limit and unavailable data", () => {
  it("AC-S1-UI-05: a 429 in one card shows the rate-limit message; other cards keep working", async () => {
    publicMode();
    installFakeApi((url) => url.searchParams.get("group_by") === "region"
      ? errorResponse(429, "rate_limited", "slow down") : undefined);
    renderAt("/dashboard");
    const regions = await screen.findByRole("region", { name: text.dashboard.salesByRegion });
    await within(regions).findByText(text.errors.rateLimited);
    const sales = await screen.findByRole("region", { name: text.dashboard.totalSales });
    await within(sales).findByText("$1.2M");
    expect(screen.queryByText(text.access.signedOut)).toBeNull();
  });

  it("S1-D15: in public mode a 503 shows the demo data message without the local command", async () => {
    for (const code of ["data_unavailable", "service_unavailable"]) {
      publicMode();
      installFakeApi((url) => url.pathname === "/v1/dimensions"
        ? errorResponse(503, code, "D:\\DealPilot AI\\data\\raw is missing") : undefined);
      const view = renderAt("/dashboard");
      await screen.findByRole("heading", { name: text.errors.dataUnavailableTitle });
      expect(screen.getByText(text.errors.demoDataUnavailable)).toBeTruthy();
      expect(screen.queryByText(text.errors.dataUnavailableHelp)).toBeNull();
      expect(document.body.textContent).not.toContain("data\\raw");
      view.unmount();
    }
  });

  it("public mode never shows the local start command for an unreachable API", async () => {
    publicMode();
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    renderAt("/data");
    await screen.findByText(text.errors.network);
    expect(screen.queryByText(text.errors.networkHelp)).toBeNull();
  });
});

describe("strings (AC-S1-UI-06)", () => {
  it("AC-S1-UI-06: the new strings live in text/en.ts with the approved English wording", () => {
    expect(text.access).toEqual({
      opening: "Opening the DealPilot AI demo...",
      invalidLink: "This link is not valid or has expired.",
      signedOut:
        "Your demo session has ended. Open your invitation link again, or ask the organizer for a new one.",
      signOut: "Sign out",
      demoNotice: "Hackathon demo. Synthetic data (seed 42). Not a commercial product.",
    });
    expect(text.errors.rateLimited).toBe("Too many requests, try again in a minute.");
    expect(text.errors.demoDataUnavailable).toBe("The demo data is temporarily unavailable.");
  });

  it("AC-S1-UI-06: no new user-facing sentence is written outside the catalog", () => {
    const sources = import.meta.glob(["../../src/**/*.{ts,tsx}", "!../../src/text/en.ts"],
      { query: "?raw", import: "default", eager: true }) as Record<string, string>;
    const sentences = [...Object.values(text.access), text.errors.rateLimited, text.errors.demoDataUnavailable];
    for (const [path, source] of Object.entries(sources)) {
      for (const sentence of sentences) expect(source, path).not.toContain(sentence);
    }
  });
});
