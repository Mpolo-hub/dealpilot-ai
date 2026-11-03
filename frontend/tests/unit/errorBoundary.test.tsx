// A page that fails to render shows an English panel, never a blank page (spec 007 section 5,
// common Error state).
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ErrorBoundary } from "../../src/components/ErrorBoundary";
import { text } from "../../src/text/en";

function Broken(): never {
  throw new Error("render failure");
}

describe("ErrorBoundary", () => {
  it("replaces a crashed page with an English message and a reload button", () => {
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    render(<ErrorBoundary><Broken /></ErrorBoundary>);
    expect(screen.getByRole("alert").textContent).toContain(text.errors.pageTitle);
    expect(screen.getByRole("button", { name: text.errors.reload })).toBeTruthy();
  });
});
