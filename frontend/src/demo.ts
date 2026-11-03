// Stage 1 public demo mode (spec 014, spec 007 amendment A7-H1). Set at build time with
// VITE_DEMO_MODE=public. When it is unset the app behaves exactly as the local RC1.

export function isPublicDemo(): boolean {
  return import.meta.env.VITE_DEMO_MODE === "public";
}
