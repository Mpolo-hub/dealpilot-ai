// Stage 1 public demo screens outside the shell (spec 014 JA-FR-05, spec 007 A7-H1 D15-H1):
// S1-a, the access page that redeems the invitation token, and S1-b, the signed-out page.
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useNavigate } from "react-router";

import { postJson } from "../api/client";
import { ACCESS_REDEEM } from "../api/endpoints";
import { isRateLimited } from "../api/errors";
import { DemoNotice } from "../components/ui";
import uiStyles from "../components/ui.module.css";
import { text } from "../text/en";
import styles from "./AccessPages.module.css";

function AccessLayout({ children }: { children: ReactNode }) {
  return (
    <div className={styles.page}>
      <DemoNotice />
      <main id="main" className={styles.main}>
        <div className={uiStyles.unavailable}>
          <h1 className={uiStyles.title}>{text.app.name}</h1>
          {children}
        </div>
      </main>
    </div>
  );
}

type Status = "pending" | "failed" | "rateLimited";

export function AccessPage() {
  const navigate = useNavigate();
  // The token is the URL fragment, which never reaches a server log.
  const [token] = useState(() => window.location.hash.slice(1));
  const [status, setStatus] = useState<Status>(token ? "pending" : "failed");
  const started = useRef(false);

  useEffect(() => {
    // Runs once, even under StrictMode's double effect in development.
    if (started.current) return;
    started.current = true;
    // Remove the token from the address bar at once (JA-FR-05 step 3).
    if (window.location.hash) {
      window.history.replaceState(window.history.state, "",
        window.location.pathname + window.location.search);
    }
    if (!token) return;
    postJson(ACCESS_REDEEM, { token }).then(
      () => navigate("/", { replace: true }),
      (error: unknown) => setStatus(isRateLimited(error) ? "rateLimited" : "failed"),
    );
  }, [navigate, token]);

  const message = status === "pending" ? text.access.opening
    : status === "rateLimited" ? text.errors.rateLimited : text.access.invalidLink;
  return (
    <AccessLayout>
      <p role={status === "pending" ? "status" : "alert"}>{message}</p>
    </AccessLayout>
  );
}

export function SignedOutPage() {
  return (
    <AccessLayout>
      <p role="alert">{text.access.signedOut}</p>
    </AccessLayout>
  );
}
