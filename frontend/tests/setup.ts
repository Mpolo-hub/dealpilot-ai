import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

import { clearApiCache } from "../src/hooks/useApi";

afterEach(() => {
  cleanup();
  clearApiCache();
  vi.unstubAllGlobals();
});
