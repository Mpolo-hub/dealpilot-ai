// English messages by spec 002 error code (spec 007 FR-06). Paths are never shown: the
// API message is offered as a detail except for `data_unavailable`, whose message may
// name the configured data folder.
import { text } from "../text/en";
import { ApiError, NetworkError } from "./client";

export function isDataUnavailable(error: unknown): boolean {
  return error instanceof ApiError && error.code === "data_unavailable";
}

export function errorMessage(error: unknown): { message: string; detail: string | null } {
  if (error instanceof NetworkError) {
    return { message: text.errors.network, detail: text.errors.networkHelp };
  }
  if (!(error instanceof ApiError)) return { message: text.errors.generic, detail: null };
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
