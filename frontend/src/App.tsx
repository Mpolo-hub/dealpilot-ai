// Routes of the first release (spec 007 section 5): four screens and "Page not found".
// Stage 1 public demo (spec 014; A7-H1 D15-H1; Annex D, S1-D13 amended 2026-11-04):
// - / and /welcome always show the Welcome page; the Dashboard is /dashboard (Annex D,
//   2026-11-04); /login is public; /access redeems an invitation link;
// - without a session, the protected pages go to /welcome; an expired session goes to
//   /login with a message; sign-out goes to /welcome.
// The server stays the control: every /v1 request without a session gets 401.
import { useEffect, useState, type ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router";

import { METADATA } from "./api/endpoints";
import { onSessionEnded, onSignedIn, onSignedOut } from "./api/session";
import { AppShell } from "./components/AppShell";
import { dashboardPath, isPublicDemo } from "./demo";
import { clearApiCache } from "./hooks/useApi";
import { AccessPage } from "./pages/AccessPages";
import { DashboardPage } from "./pages/DashboardPage";
import { DataPage } from "./pages/DataPage";
import { LoginPage } from "./pages/LoginPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { ProductsPage } from "./pages/ProductsPage";
import { SalesAnalysisPage } from "./pages/SalesAnalysisPage";
import { WelcomePage } from "./pages/WelcomePage";
import { text } from "./text/en";

type Auth = "checking" | "in" | "out" | "expired";

/** Does the browser hold a valid session? One cheap /v1 call: 401 means no. */
async function probeSession(): Promise<Auth> {
  try {
    const response = await fetch(METADATA, { credentials: "same-origin" });
    return response.status === 401 ? "out" : "in";
  } catch {
    return "in"; // network trouble: let the pages show their own error states
  }
}

function usePublicAuth(enabled: boolean, probe: boolean): Auth {
  const [auth, setAuth] = useState<Auth>(enabled ? "checking" : "in");
  // The invitation link page (/access) redeems first; it needs no probe.
  useEffect(() => {
    if (!enabled || !probe) return undefined;
    let active = true;
    probeSession().then((result) => {
      if (active) setAuth((current) => (current === "checking" ? result : current));
    });
    return () => {
      active = false;
    };
  }, [enabled, probe]);
  useEffect(() => {
    if (!enabled) return undefined;
    const stops = [
      onSessionEnded(() => {
        clearApiCache();
        setAuth("expired");
      }),
      onSignedOut(() => {
        clearApiCache();
        setAuth("out");
      }),
      onSignedIn(() => {
        clearApiCache();
        setAuth("in");
      }),
    ];
    return () => stops.forEach((stop) => stop());
  }, [enabled]);
  return auth;
}

export function App() {
  const publicDemo = isPublicDemo();
  const onAccessPage = useLocation().pathname === "/access";
  const auth = usePublicAuth(publicDemo, !onAccessPage);

  let shell: ReactNode = <AppShell />;
  if (publicDemo && auth === "checking") {
    shell = <p className="visually-hidden" role="status">{text.common.loading}</p>;
  } else if (publicDemo && auth === "out") {
    shell = <Navigate to="/welcome" replace />;
  } else if (publicDemo && auth === "expired") {
    shell = <Navigate to="/login" replace state={{ expired: true }} />;
  }

  return (
    <Routes>
      {publicDemo && <Route path="access" element={<AccessPage />} />}
      {publicDemo && <Route index element={<WelcomePage signedIn={auth === "in"} />} />}
      {publicDemo && <Route path="welcome" element={<WelcomePage signedIn={auth === "in"} />} />}
      {publicDemo && (
        <Route path="login" element={auth === "in" ? <Navigate to={dashboardPath()} replace /> : <LoginPage />} />
      )}
      <Route element={shell}>
        {publicDemo
          ? <Route path="dashboard" element={<DashboardPage />} />
          : <Route index element={<DashboardPage />} />}
        <Route path="data" element={<DataPage />} />
        <Route path="analysis" element={<SalesAnalysisPage />} />
        <Route path="products" element={<ProductsPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
