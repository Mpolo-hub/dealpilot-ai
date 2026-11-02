import { render } from "@testing-library/react";
import { useEffect } from "react";
import { MemoryRouter, useLocation } from "react-router";

import { App } from "../src/App";

export let currentLocation = "";

function LocationProbe() {
  const location = useLocation();
  useEffect(() => {
    currentLocation = `${location.pathname}${location.search}`;
  }, [location]);
  return null;
}

/** Render the whole app at a URL, as the browser would (routes, shell, page). */
export function renderAt(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <App />
      <LocationProbe />
    </MemoryRouter>,
  );
}
