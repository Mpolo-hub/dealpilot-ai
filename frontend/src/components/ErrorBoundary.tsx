// Shows an English error panel instead of a blank page if a page fails to render
// (spec 007 section 5, common Error state). The shell keys it by path, so going to another page recovers.
import { Component, type ReactNode } from "react";

import { text } from "../text/en";
import styles from "./ui.module.css";

export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true };
  }

  componentDidCatch(error: unknown): void {
    console.error("DealPilot page error", error);
  }

  render(): ReactNode {
    if (!this.state.failed) return this.props.children;
    return (
      <div className={styles.unavailable} role="alert">
        <h1 className={styles.title}>{text.errors.pageTitle}</h1>
        <p>{text.errors.pageBody}</p>
        <div>
          <button type="button" className={styles.button} onClick={() => window.location.reload()}>
            {text.errors.reload}
          </button>
        </div>
      </div>
    );
  }
}
