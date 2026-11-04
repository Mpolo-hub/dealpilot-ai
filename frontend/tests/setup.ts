import { cleanup, configure } from "@testing-library/react";
import { afterEach, vi } from "vitest";

import { clearApiCache } from "../src/hooks/useApi";

// findBy and waitFor wait up to 5 s instead of 1 s: with 8 test files running in parallel
// a page can need more than 1 s to render on a busy machine (timing only, no behavior).
configure({ asyncUtilTimeout: 5000 });

afterEach(() => {
  cleanup();
  clearApiCache();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});
