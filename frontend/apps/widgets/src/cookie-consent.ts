import { css, html, LitElement } from "lit";

import { t } from "./strings";

const COOKIE = "tt_consent";
const VERSION = 1;

export interface CookieChoice {
  necessary: true;
  analytics: boolean;
  marketing: boolean;
  version: number;
}

export function readChoice(): CookieChoice | null {
  const raw = document.cookie
    .split("; ")
    .find((c) => c.startsWith(`${COOKIE}=`))
    ?.slice(COOKIE.length + 1);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(decodeURIComponent(raw)) as CookieChoice;
    return parsed.version === VERSION ? parsed : null;
  } catch {
    return null;
  }
}

/**
 * `<tt-cookie-consent>`: cookie banner for tenant websites embedding TutorTrack widgets
 * (E29 FR-29-3). Same cookie as the apps; emits `tt-cookie-consent` on window with the
 * choice so host pages can load analytics only when allowed. The text follows the page's
 * locale (see strings.ts: `data-locale` on the loader script, else the page's `lang`), and the
 * `heading`, `body`, `accept-label` and `reject-label` attributes, or
 * `window.TutorTrackWidgets.messages`, can still replace any of it.
 */
export class TtCookieConsent extends LitElement {
  static properties = {
    heading: { type: String },
    body: { type: String },
    acceptLabel: { type: String, attribute: "accept-label" },
    rejectLabel: { type: String, attribute: "reject-label" },
    open: { state: true },
  };

  static styles = css`
    :host {
      position: fixed;
      inset: auto 0 0 0;
      z-index: 2147483000;
      font-family: var(--tt-font, inherit);
      font-size: 0.875rem;
      line-height: 1.5;
    }
    /* Over the page, so it needs its own ground: the host's own Canvas colours. */
    section {
      background: var(--tt-surface, Canvas);
      color: var(--tt-text, CanvasText);
      border-top: 1px solid
        var(--tt-border, color-mix(in srgb, var(--tt-text, CanvasText) 18%, transparent));
      padding: 16px;
    }
    strong {
      font-weight: 600;
    }
    .actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: 8px;
    }
    /* Accept and reject carry equal weight, so neither choice is nudged. */
    button {
      font: inherit;
      font-weight: 500;
      min-height: 40px;
      padding: 8px 16px;
      border-radius: var(--tt-radius, 8px);
      border: 0;
      cursor: pointer;
      background: var(--tt-brand-color, #2a54a2);
      color: var(--tt-on-brand, #fff);
    }
    button:focus-visible {
      outline: 2px solid var(--tt-link-color, #2a54a2);
      outline-offset: 2px;
    }
  `;

  declare heading: string | undefined;
  declare body: string | undefined;
  declare acceptLabel: string | undefined;
  declare rejectLabel: string | undefined;
  declare open: boolean;

  constructor() {
    super();
    this.open = false;
  }

  connectedCallback() {
    super.connectedCallback();
    this.open = readChoice() === null;
  }

  private choose(all: boolean) {
    const value: CookieChoice = {
      necessary: true,
      analytics: all,
      marketing: all,
      version: VERSION,
    };
    document.cookie = `${COOKIE}=${encodeURIComponent(JSON.stringify(value))}; Max-Age=${
      180 * 24 * 3600
    }; Path=/; SameSite=Lax`;
    window.dispatchEvent(new CustomEvent("tt-cookie-consent", { detail: value }));
    this.open = false;
  }

  render() {
    if (!this.open) return html``;
    const heading = this.heading || t("cookieHeading");
    return html`<section role="region" aria-label=${heading}>
      <strong>${heading}</strong>
      <div>${this.body || t("cookieBody")}</div>
      <div class="actions">
        <button @click=${() => this.choose(true)}>${this.acceptLabel || t("cookieAccept")}</button>
        <button @click=${() => this.choose(false)}>${this.rejectLabel || t("cookieReject")}</button>
      </div>
    </section>`;
  }
}

if (!customElements.get("tt-cookie-consent")) {
  customElements.define("tt-cookie-consent", TtCookieConsent);
}

declare global {
  interface HTMLElementTagNameMap {
    "tt-cookie-consent": TtCookieConsent;
  }
}
