// Routes of the first release (spec 007 section 5): four screens and "Page not found".
// In the Stage 1 public demo (A7-H1 D15-H1) also the access page, outside the shell, and
// the signed-out page, shown once the session has ended.
import { useEffect, useState } from "react";
import { Route, Routes } from "react-router";

import { onSessionEnded } from "./api/session";
import { AppShell } from "./components/AppShell";
import { isPublicDemo } from "./demo";
import { clearApiCache } from "./hooks/useApi";
import { AccessPage, SignedOutPage } from "./pages/AccessPages";
import { DashboardPage } from "./pages/DashboardPage";
import { DataPage } from "./pages/DataPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { ProductsPage } from "./pages/ProductsPage";
import { SalesAnalysisPage } from "./pages/SalesAnalysisPage";

export function App() {
  const publicDemo = isPublicDemo();
  const [signedOut, setSignedOut] = useState(false);

  useEffect(() => {
    if (!publicDemo) return undefined;
    return onSessionEnded(() => {
      clearApiCache();
      setSignedOut(true);
    });
  }, [publicDemo]);

  if (signedOut) return <SignedOutPage />;
  return (
    <Routes>
      {publicDemo && <Route path="access" element={<AccessPage />} />}
      <Route element={<AppShell />}>
        <Route index element={<DashboardPage />} />
        <Route path="data" element={<DataPage />} />
        <Route path="analysis" element={<SalesAnalysisPage />} />
        <Route path="products" element={<ProductsPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
