// Invitation Login page (/login, public): spec 014 Annex D, S1-D13 amended 2026-11-04.
// Design reference: DealDesign/auth.png (split card: blue panel with the value proposition,
// light panel with the form). Only an invitation code exists: no username, password,
// "remember me", password reset or sign-up, so none is shown.
// The code stays in component memory only: never in storage or the URL (spec 014 JA-SR-02).
import { useId, useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router";

import { accessFailure, extractCode, redeemInvitation, type AccessFailure } from "../api/access";
import { DemoNotice } from "../components/ui";
import { Icon } from "../components/Icons";
import { text } from "../text/en";
import styles from "./PublicPages.module.css";

type Status = "idle" | "empty" | "pending" | AccessFailure;

const MESSAGES: Record<Exclude<Status, "idle" | "pending">, string> = {
  empty: text.login.empty,
  invalid: text.access.invalidLink,
  rateLimited: text.errors.rateLimited,
  unavailable: text.login.unavailable,
};

export function LoginPage() {
  const t = text.login;
  const navigate = useNavigate();
  const expired = Boolean((useLocation().state as { expired?: boolean } | null)?.expired);
  const [value, setValue] = useState("");
  const [visible, setVisible] = useState(false);
  const [status, setStatus] = useState<Status>("idle");
  const fieldId = useId();
  const messageId = useId();

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const code = extractCode(value);
    if (!code) {
      setStatus("empty");
      return;
    }
    setStatus("pending");
    redeemInvitation(code).then(
      () => {
        setValue("");
        navigate("/", { replace: true });
      },
      (error: unknown) => setStatus(accessFailure(error)),
    );
  };

  const message = status === "idle" || status === "pending" ? null : MESSAGES[status];
  return (
    <div className={styles.page}>
      <DemoNotice />
      <main id="main" className={styles.loginMain}>
        <div className={styles.authCard}>
          <section className={styles.authAside}>
            <p className={styles.asideTitle}>{t.asideTitle}</p>
            <p className={styles.asideBody}>{t.asideBody}</p>
          </section>
          <section className={styles.authForm} aria-labelledby="login-title">
            <div className={`${styles.brand} ${styles.brandDark}`}>
              <span className={styles.logo}><Icon name="logo" size={22} /></span>
              <span className={styles.brandName}>DealPilot <span className={styles.brandAccent}>AI</span></span>
            </div>
            <h1 id="login-title" className={styles.formTitle}>{t.title}</h1>
            {expired && status === "idle" && <p className={styles.notice} role="status">{text.access.signedOut}</p>}
            <p className={styles.formLead}>{t.lead}</p>
            <form method="post" onSubmit={submit} noValidate>
              <label className={styles.label} htmlFor={fieldId}>{t.label}</label>
              <div className={styles.field}>
                <input id={fieldId} className={styles.input} type={visible ? "text" : "password"}
                  value={value} onChange={(e) => setValue(e.target.value)} autoComplete="off"
                  autoCapitalize="none" spellCheck={false} aria-invalid={status === "empty" || status === "invalid"}
                  aria-describedby={message ? messageId : undefined} disabled={status === "pending"} />
                <button type="button" className={styles.toggle} aria-pressed={visible}
                  aria-controls={fieldId} onClick={() => setVisible((v) => !v)}>
                  {visible ? t.hide : t.show}
                </button>
              </div>
              {message && <p id={messageId} className={styles.error} role="alert">{message}</p>}
              <button type="submit" className={styles.primaryButton} disabled={status === "pending"}>
                {status === "pending" ? t.submitting : t.submit}
              </button>
              {status === "pending" && <p className="visually-hidden" role="status">{t.submitting}</p>}
            </form>
            <p className={styles.formNote}>{t.noInvitation}</p>
            <Link to="/welcome" className={styles.backLink}>{t.back}</Link>
          </section>
        </div>
      </main>
    </div>
  );
}
