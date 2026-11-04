// Welcome (/welcome) and invitation Login (/login) pages: spec 014 Annex D, S1-D13 amended
// 2026-11-04. Public demo mode is set with vi.stubEnv; local mode must stay unchanged.
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { extractCode } from "../../src/api/access";
import { text } from "../../src/text/en";
import { errorResponse, installFakeApi } from "../fakeApi";
import { currentLocation, renderAt } from "../render";

const CODE = "Abc123_-xyzXYZ0987654321abcdefABCDEF0123456";

function publicMode() {
  vi.stubEnv("VITE_DEMO_MODE", "public");
}

/** Fake API where the visitor has no session until a redeem succeeds. */
function signedOutApi(redeem: () => Response | Promise<Response>) {
  let signedIn = false;
  return installFakeApi((url) => {
    if (url.pathname === "/access/redeem") {
      return Promise.resolve(redeem()).then((r) => {
        if (r.status === 204) signedIn = true;
        return r;
      });
    }
    if (url.pathname.startsWith("/v1/") && !signedIn) return errorResponse(401, "unauthorized");
    return undefined;
  });
}

function redeemBodies(): unknown[] {
  return (vi.mocked(fetch).mock.calls as unknown as [string, RequestInit | undefined][])
    .filter(([p]) => p === "/access/redeem").map(([, init]) => JSON.parse(String(init?.body)));
}

async function typeAndSubmit(value: string) {
  const field = await screen.findByLabelText(text.login.label);
  await userEvent.type(field, value);
  await userEvent.click(screen.getByRole("button", { name: text.login.submit }));
}

describe("Welcome page", () => {
  it("renders the brand, value proposition and synthetic-data notice, with no data call", async () => {
    publicMode();
    const requested = signedOutApi(() => new Response(null, { status: 204 }));
    renderAt("/welcome");
    expect(await screen.findByRole("heading", { name: text.welcome.title, level: 1 })).toBeTruthy();
    expect(screen.getByText(text.welcome.dataBody)).toBeTruthy();
    expect(screen.getByText(text.access.demoNotice)).toBeTruthy();
    expect(requested.filter((p) => p.startsWith("/v1/") && p !== "/v1/metadata")).toEqual([]);
  });

  it("the call to action opens /login", async () => {
    publicMode();
    signedOutApi(() => new Response(null, { status: 204 }));
    renderAt("/welcome");
    await userEvent.click(await screen.findByRole("link", { name: new RegExp(text.welcome.cta) }));
    expect(currentLocation).toBe("/login");
    expect(await screen.findByRole("heading", { name: text.login.title, level: 1 })).toBeTruthy();
  });
});

describe("Login page", () => {
  it("accepts a bare code and posts it to /access/redeem, then opens the Dashboard", async () => {
    publicMode();
    signedOutApi(() => new Response(null, { status: 204 }));
    renderAt("/login");
    await typeAndSubmit(CODE);
    await screen.findByRole("heading", { name: text.dashboard.title, level: 1 });
    expect(currentLocation).toBe("/dashboard");
    expect(redeemBodies()).toEqual([{ token: CODE }]);
  });

  it("accepts a full invitation link and sends only the part after #", async () => {
    publicMode();
    signedOutApi(() => new Response(null, { status: 204 }));
    renderAt("/login");
    await typeAndSubmit(`https://dealpilot-ai-demo.onrender.com/access#${CODE}`);
    await screen.findByRole("heading", { name: text.dashboard.title, level: 1 });
    expect(redeemBodies()).toEqual([{ token: CODE }]);
    expect(extractCode(`  x/access#${CODE}  `)).toBe(CODE);
  });

  it("an empty field shows a message and sends nothing", async () => {
    publicMode();
    signedOutApi(() => new Response(null, { status: 204 }));
    renderAt("/login");
    await screen.findByLabelText(text.login.label);
    await userEvent.click(screen.getByRole("button", { name: text.login.submit }));
    expect((await screen.findByRole("alert")).textContent).toBe(text.login.empty);
    expect(redeemBodies()).toEqual([]);
  });

  it.each([
    ["invalid, expired or revoked (401)", () => errorResponse(401, "invalid_link"), text.access.invalidLink],
    ["refused (403)", () => errorResponse(403, "forbidden"), text.access.invalidLink],
    ["too many attempts (429)", () => errorResponse(429, "rate_limited"), text.errors.rateLimited],
    ["unavailable (503)", () => errorResponse(503, "service_unavailable"), text.login.unavailable],
  ])("%s shows the right message and stays on /login", async (_name, response, message) => {
    publicMode();
    signedOutApi(response);
    renderAt("/login");
    await typeAndSubmit(CODE);
    expect((await screen.findByRole("alert")).textContent).toBe(message);
    expect(currentLocation).toBe("/login");
  });

  it("a network error (service asleep) shows the waking-up message", async () => {
    publicMode();
    signedOutApi(() => Promise.reject(new TypeError("Failed to fetch")));
    renderAt("/login");
    await typeAndSubmit(CODE);
    expect((await screen.findByRole("alert")).textContent).toBe(text.login.unavailable);
  });

  it("shows a loading state while the request runs", async () => {
    publicMode();
    let release: (r: Response) => void = () => undefined;
    signedOutApi(() => new Promise<Response>((resolve) => { release = resolve; }));
    renderAt("/login");
    await typeAndSubmit(CODE);
    expect(screen.getByRole("button", { name: text.login.submitting })).toHaveProperty("disabled", true);
    release(new Response(null, { status: 204 }));
    await screen.findByRole("heading", { name: text.dashboard.title, level: 1 });
  });

  it("the show/hide toggle switches the field type and the code is never stored", async () => {
    publicMode();
    signedOutApi(() => errorResponse(401, "invalid_link"));
    renderAt("/login");
    const field = await screen.findByLabelText(text.login.label);
    expect(field.getAttribute("type")).toBe("password");
    await userEvent.click(screen.getByRole("button", { name: text.login.show }));
    expect(field.getAttribute("type")).toBe("text");
    await typeAndSubmit(CODE);
    await screen.findByRole("alert");
    const stored = JSON.stringify({ ...localStorage }) + JSON.stringify({ ...sessionStorage });
    expect(stored).not.toContain(CODE);
    expect(window.location.href).not.toContain(CODE);
    expect(currentLocation).not.toContain(CODE);
  });

  it("an already signed-in visitor opening /login goes to the Dashboard", async () => {
    publicMode();
    installFakeApi();
    renderAt("/login");
    await screen.findByRole("heading", { name: text.dashboard.title, level: 1 });
    expect(currentLocation).toBe("/dashboard");
  });
});

describe("routing without a session", () => {
  it.each(["/dashboard", "/analysis", "/products", "/data"])(
    "a visitor without a session who opens %s goes to /welcome",
    async (path) => {
      publicMode();
      signedOutApi(() => new Response(null, { status: 204 }));
      renderAt(path);
      await screen.findByRole("heading", { name: text.welcome.title, level: 1 });
      await waitFor(() => expect(currentLocation).toBe("/welcome"));
    },
  );

  it("local mode is unchanged: no /welcome or /login routes, the Dashboard opens", async () => {
    installFakeApi();
    renderAt("/");
    await screen.findByRole("heading", { name: text.dashboard.title, level: 1 });
    for (const path of ["/welcome", "/login"]) {
      const view = renderAt(path);
      await screen.findByRole("heading", { name: text.notFound.title });
      view.unmount();
    }
  });
});

describe("site root in public mode (Annex D, 2026-11-04)", () => {
  it("/ always shows the Welcome page, even with a valid session; its button opens /dashboard", async () => {
    publicMode();
    installFakeApi();                                   // the session is valid
    renderAt("/");
    await screen.findByRole("heading", { name: text.welcome.title, level: 1 });
    expect(currentLocation).toBe("/");
    const cta = await screen.findByRole("link", { name: new RegExp(text.welcome.cta) });
    await waitFor(() => expect(cta.getAttribute("href")).toBe("/dashboard"));
    await userEvent.click(cta);
    await screen.findByRole("heading", { name: text.dashboard.title, level: 1 });
    expect(currentLocation).toBe("/dashboard");
  });

  it("/ without a session shows Welcome; its button opens /login", async () => {
    publicMode();
    signedOutApi(() => new Response(null, { status: 204 }));
    renderAt("/");
    await screen.findByRole("heading", { name: text.welcome.title, level: 1 });
    const cta = screen.getByRole("link", { name: new RegExp(text.welcome.cta) });
    await waitFor(() => expect(cta.getAttribute("href")).toBe("/login"));
    expect(currentLocation).toBe("/");
  });

  it("the Dashboard navigation entry points to /dashboard in public mode", async () => {
    publicMode();
    installFakeApi();
    renderAt("/analysis");
    const nav = await screen.findByRole("navigation", { name: text.app.mainNavigation });
    expect(within(nav).getByRole("link", { name: text.nav.dashboard }).getAttribute("href")).toBe("/dashboard");
  });

  it("the invitation link /access lands on /dashboard", async () => {
    publicMode();
    signedOutApi(() => new Response(null, { status: 204 }));
    window.history.replaceState(null, "", "/access#abcdefghijklmnopqrstuvwxyz0123456789ABCD");
    renderAt("/access");
    await screen.findByRole("heading", { name: text.dashboard.title, level: 1 });
    expect(currentLocation).toBe("/dashboard");
    window.history.replaceState(null, "", "/");
  });

  it("local mode keeps the Dashboard at / with its navigation entry at /", async () => {
    installFakeApi();
    renderAt("/");
    await screen.findByRole("heading", { name: text.dashboard.title, level: 1 });
    const nav = screen.getByRole("navigation", { name: text.app.mainNavigation });
    expect(within(nav).getByRole("link", { name: text.nav.dashboard }).getAttribute("href")).toBe("/");
    expect(currentLocation).toBe("/");
  });
});
