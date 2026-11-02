// Routes of the first release (spec 007 section 5): four screens and "Page not found".
import { Route, Routes } from "react-router";

import { AppShell } from "./components/AppShell";
import { DashboardPage } from "./pages/DashboardPage";
import { DataPage } from "./pages/DataPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { ProductsPage } from "./pages/ProductsPage";
import { SalesAnalysisPage } from "./pages/SalesAnalysisPage";

export function App() {
  return (
    <Routes>
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
