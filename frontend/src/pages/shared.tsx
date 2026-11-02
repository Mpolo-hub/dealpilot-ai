// Helpers shared by the four pages.
import type { ReactNode } from "react";

import { ErrorPanel, Skeleton } from "../components/ui";
import type { ApiState } from "../hooks/useApi";

/** Renders a card body for one request: skeleton, error panel with retry, or the content. */
export function Loaded<T>({ state, retry, height, children }: {
  state: ApiState<T>; retry: () => void; height?: number; children: (data: T) => ReactNode;
}) {
  if (state.status === "loading") return <Skeleton height={height} />;
  if (state.status === "error") return <ErrorPanel error={state.error} onRetry={retry} />;
  return <>{children(state.data)}</>;
}
