// Stage 1 public demo mode (spec 014, spec 007 amendment A7-H1). Set at build time with
// VITE_DEMO_MODE=public. When it is unset the app behaves exactly as the local RC1.

/** Where the Dashboard lives: /dashboard in the public demo (/ is the Welcome page,
 * spec 014 Annex D, 2026-11-04), / in local mode as before. */
export function dashboardPath(): string {
  return isPublicDemo() ? "/dashboard" : "/";
}

export function isPublicDemo(): boolean {
  return import.meta.env.VITE_DEMO_MODE === "public";
}
