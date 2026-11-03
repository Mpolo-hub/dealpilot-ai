// Welcome page (/welcome, public, no data): spec 014 Annex D, S1-D13 amended 2026-11-04.
// Design reference: DealDesign/welcome.png (brand header, headline, two feature cards,
// call to action, "secure invitation-only access").
import { Link } from "react-router";

import { DemoNotice } from "../components/ui";
import { Icon } from "../components/Icons";
import { text } from "../text/en";
import styles from "./PublicPages.module.css";

export function WelcomePage() {
  const t = text.welcome;
  return (
    <div className={styles.page}>
      <DemoNotice />
      <main id="main" className={styles.welcomeMain}>
        <section className={styles.hero} aria-labelledby="welcome-title">
          <div className={styles.brand}>
            <span className={styles.logo}><Icon name="logo" size={22} /></span>
            <span className={styles.brandName}>DealPilot <span className={styles.brandAccent}>AI</span></span>
          </div>
          <h1 id="welcome-title" className={styles.heroTitle}>{t.title}</h1>
          <p className={styles.heroLead}>{t.lead}</p>
          <ul className={styles.features}>
            <li className={styles.feature}>
              <Icon name="trend" />
              <h2 className={styles.featureTitle}>{t.salesTitle}</h2>
              <p className={styles.featureBody}>{t.salesBody}</p>
            </li>
            <li className={styles.feature}>
              <Icon name="box" />
              <h2 className={styles.featureTitle}>{t.productsTitle}</h2>
              <p className={styles.featureBody}>{t.productsBody}</p>
            </li>
            <li className={styles.feature}>
              <Icon name="data" />
              <h2 className={styles.featureTitle}>{t.dataTitle}</h2>
              <p className={styles.featureBody}>{t.dataBody}</p>
            </li>
          </ul>
        </section>
        <section className={styles.ctaPanel} aria-label={t.cta}>
          <Link to="/login" className={styles.primaryButton}>
            {t.cta} <span aria-hidden="true">→</span>
          </Link>
          <p className={styles.secure}><Icon name="info" size={14} /> {t.secure}</p>
        </section>
      </main>
    </div>
  );
}
