import { css, html, LitElement } from "lit";

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
 * choice so host pages can load analytics only when allowed. Text is configurable through
 * attributes so tenants can translate it.
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
      font: var(--tt-font, 14px system-ui, sans-serif);
    }
    section {
      background: var(--tt-surface, #fff);
      color: var(--tt-text, #111827);
      border-top: 1px solid var(--tt-border, #e5e7eb);
      padding: 16px;
    }
    .actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: 8px;
    }
    button {
      font: inherit;
      padding: 8px 14px;
      border-radius: 6px;
      border: 0;
      cursor: pointer;
      background: var(--tt-brand-color, #2563eb);
      color: #fff;
    }
    button:focus-visible {
      outline: 2px solid var(--tt-brand-color, #2563eb);
      outline-offset: 2px;
    }
  `;

  declare heading: string;
  declare body: string;
  declare acceptLabel: string;
  declare rejectLabel: string;
  declare open: boolean;

  constructor() {
    super();
    this.heading = "Cookies";
    this.body =
      "We use necessary cookies to make this site work. With your permission we also use analytics and marketing cookies.";
    this.acceptLabel = "Accept all";
    this.rejectLabel = "Reject non-essential";
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
    return html`<section role="region" aria-label=${this.heading}>
      <strong>${this.heading}</strong>
      <div>${this.body}</div>
      <div class="actions">
        <button @click=${() => this.choose(true)}>${this.acceptLabel}</button>
        <button @click=${() => this.choose(false)}>${this.rejectLabel}</button>
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
