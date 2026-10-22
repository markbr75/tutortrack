import { css, html, LitElement } from "lit";

/** `<tt-powered-by org="Bright Minds">`: reference widget proving the build and theming. */
export class TtPoweredBy extends LitElement {
  static properties = { org: { type: String } };

  static styles = css`
    :host {
      display: inline-block;
      font-family: var(--tt-font, inherit);
      font-size: 0.75em;
      color: var(--tt-muted-color, color-mix(in srgb, currentColor 72%, transparent));
    }
    a {
      color: inherit;
      text-underline-offset: 0.2em;
    }
  `;

  declare org: string;

  constructor() {
    super();
    this.org = "";
  }

  render() {
    const label = this.org ? `${this.org} · ` : "";
    return html`<span
      >${label}Powered by
      <a href="https://tutortrack.app" target="_blank" rel="noopener">TutorTrack</a></span
    >`;
  }
}

if (!customElements.get("tt-powered-by")) {
  customElements.define("tt-powered-by", TtPoweredBy);
}

declare global {
  interface HTMLElementTagNameMap {
    "tt-powered-by": TtPoweredBy;
  }
}
