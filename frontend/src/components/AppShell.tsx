// Application shell (spec 007 sections 5 and 9): sidebar with the four F1 screens only
// (D6), a top bar with the menu button on small screens, and the page content.
import { useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router";

import { text } from "../text/en";
import styles from "./AppShell.module.css";
import { ErrorBoundary } from "./ErrorBoundary";
import { Icon, type IconName } from "./Icons";

const NAV: { to: string; label: string; icon: IconName }[] = [
  { to: "/", label: text.nav.dashboard, icon: "dashboard" },
  { to: "/data", label: text.nav.data, icon: "data" },
  { to: "/analysis", label: text.nav.analysis, icon: "analysis" },
  { to: "/products", label: text.nav.products, icon: "products" },
];

export function AppShell() {
  const [open, setOpen] = useState(false);
  const location = useLocation();
  const [lastPath, setLastPath] = useState(location.pathname);
  if (lastPath !== location.pathname) {
    // Close the phone menu after navigation.
    setLastPath(location.pathname);
    setOpen(false);
  }

  return (
    <div className={styles.shell}>
      <a className={styles.skip} href="#main">{text.app.skipToContent}</a>
      <aside className={`${styles.sidebar} ${open ? styles.open : ""}`}>
        <div className={styles.brand}>
          <span className={styles.logo}><Icon name="logo" size={22} /></span>
          <span className={styles.brandName}>{text.app.name}</span>
        </div>
        <nav aria-label={text.app.mainNavigation} id="main-navigation">
          <ul className={styles.navList}>
            {NAV.map((item) => (
              <li key={item.to}>
                <NavLink to={item.to} end={item.to === "/"} title={item.label}
                  className={({ isActive }) => `${styles.navItem} ${isActive ? styles.active : ""}`}>
                  <Icon name={item.icon} />
                  <span className={styles.navLabel}>{item.label}</span>
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
      </aside>
      {open && <div className={styles.backdrop} onClick={() => setOpen(false)} aria-hidden="true" />}
      <div className={styles.body}>
        <header className={styles.topbar}>
          <button type="button" className={styles.menuButton} aria-expanded={open}
            aria-controls="main-navigation" onClick={() => setOpen(!open)}>
            <Icon name={open ? "close" : "menu"} size={20} />
            <span className="visually-hidden">{open ? text.app.closeMenu : text.app.menu}</span>
          </button>
          <span className={styles.topbarBrand}>{text.app.name}</span>
        </header>
        <main id="main" className={styles.main} tabIndex={-1}>
          <ErrorBoundary key={location.pathname}>
            <Outlet />
          </ErrorBoundary>
        </main>
      </div>
    </div>
  );
}
