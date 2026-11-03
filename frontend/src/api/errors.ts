// English messages by spec 002 error code (spec 007 FR-06). Paths are never shown: the
// API message is offered as a detail except for `data_unavailable`, whose message may
// name the configured data folder. In the Stage 1 public demo (A7-H1, S1-D15) no local
// command or path is shown either.
import { isPublicDemo } from "../demo";
import { text } from "../text/en";
import { ApiError, NetworkError } from "./client";

export function isDataUnavailable(error: unknown): boolean {
  if (!(error instanceof ApiError)) return false;
  if (error.code === "data_unavailable") return true;
  return isPublicDemo() && error.code === "service_unavailable";
}

export function isRateLimited(error: unknown): boolean {
  return error instanceof ApiError && (error.code === "rate_limited" || error.status === 429);
}

export function errorMessage(error: unknown): { message: string; detail: string | null } {
  const publicDemo = isPublicDemo();
  if (error instanceof NetworkError) {
    return { message: text.errors.network, detail: publicDemo ? null : text.errors.networkHelp };
  }
  if (!(error instanceof ApiError)) return { message: text.errors.generic, detail: null };
  if (isRateLimited(error)) return { message: text.errors.rateLimited, detail: null };
  if (publicDemo && isDataUnavailable(error)) {
    return { message: text.errors.demoDataUnavailable, detail: null };
  }
  const detail = error.message || null;
  switch (error.code) {
    case "data_unavailable":
      return { message: text.errors.dataUnavailable, detail: null };
    case "result_too_large":
      return { message: text.errors.resultTooLarge, detail };
    case "date_out_of_range":
    case "invalid_date":
    case "invalid_date_range":
      return { message: text.errors.dates, detail };
    case "invalid_filter":
      return { message: text.errors.filter, detail };
    default:
      return { message: text.errors.generic, detail };
  }
}
