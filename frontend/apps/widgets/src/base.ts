import { css, html, LitElement, nothing, type PropertyValues } from "lit";

import { applyTheme, branding, widgetConfig, type Branding, type WidgetConfig } from "./runtime";
import { t } from "./strings";

/**
 * Base for TutorTrack widgets: Shadow DOM isolation, brand theming through CSS custom
 * properties, optional `widget="w-..."` configuration from the admin's widget builder,
 * and the "Powered by" footer unless the organisation is white-labelled.
 */
export class TtWidget extends LitElement {
  static properties = {
    widget: { type: String },
    brand: { state: true },
    config: { state: true },
    failed: { state: true },
  };

  /**
   * Quiet register proportions that take the host page's font, colour and ground: ink and
   * rules are drawn from the inherited text colour, so a widget reads on a light or a dark
   * site; the tenant's colour fills primary buttons only. Tenants can still set any `--tt-*`
   * property (the widget builder sets `--tt-radius`).
   */
  static baseStyles = css`
    :host {
      display: block;
      font-family: var(--tt-font, inherit);
      color: var(--tt-text, inherit);
      line-height: 1.5;
      font-variant-numeric: tabular-nums;
      --tt-muted: var(--tt-muted-color, color-mix(in srgb, currentColor 72%, transparent));
      --tt-rule: var(--tt-border, color-mix(in srgb, currentColor 18%, transparent));
      --tt-edge: var(--tt-field, color-mix(in srgb, currentColor 55%, transparent));
    }
    *,
    *::before,
    *::after {
      box-sizing: border-box;
    }
    h2,
    h3 {
      font-size: 1em;
      font-weight: 600;
      line-height: 1.4;
    }
    p {
      margin: 0 0 8px;
    }
    a {
      color: var(--tt-link-color, LinkText);
      text-underline-offset: 0.2em;
    }
    button,
    .button {
      font: inherit;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      min-height: 44px;
      padding: 8px 16px;
      border: 1px solid transparent;
      border-radius: var(--tt-radius, 8px);
      background: var(--tt-brand-color, #2a54a2);
      color: var(--tt-on-brand, #fff);
      font-weight: 500;
      cursor: pointer;
      text-decoration: none;
    }
    button:hover,
    .button:hover {
      opacity: 0.9;
    }
    button:disabled {
      opacity: 0.5;
      cursor: not-allowed;
    }
    button.secondary {
      background: transparent;
      color: inherit;
      border-color: var(--tt-rule);
    }
    button.secondary:hover {
      opacity: 1;
      background: color-mix(in srgb, currentColor 6%, transparent);
    }
    :focus-visible {
      outline: 2px solid var(--tt-link-color, #2a54a2);
      outline-offset: 2px;
    }
    input,
    select,
    textarea {
      font: inherit;
      width: 100%;
      min-height: 44px;
      padding: 8px 12px;
      border: 1px solid var(--tt-edge);
      border-radius: var(--tt-radius, 8px);
      background: var(--tt-surface, transparent);
      color: inherit;
    }
    select option {
      color: initial;
    }
    label {
      display: block;
      font-weight: 500;
      margin-bottom: 4px;
    }
    fieldset {
      border: 0;
      padding: 0;
      margin: 0;
      min-width: 0;
    }
    legend {
      padding: 0;
      font-weight: 500;
      margin-bottom: 8px;
    }
    .muted {
      color: var(--tt-muted);
    }
    .card {
      background: var(--tt-surface, transparent);
      border: 1px solid var(--tt-rule);
      border-radius: calc(var(--tt-radius, 8px) + 4px);
      padding: 16px 20px;
    }
    .sr-only {
      position: absolute;
      width: 1px;
      height: 1px;
      overflow: hidden;
      clip: rect(0 0 0 0);
      white-space: nowrap;
    }
    .powered {
      margin: 16px 0 0;
      font-size: 0.75em;
    }
    .powered a {
      color: inherit;
    }
    [role="alert"],
    .error {
      color: var(--tt-danger, #b42318);
    }
  `;

  declare widget: string;
  declare brand: Branding | undefined;
  declare config: WidgetConfig | undefined;
  declare failed: boolean;

  constructor() {
    super();
    this.widget = "";
    this.failed = false;
  }

  /** Options from the widget builder (empty when used without `widget=`). */
  protected get options(): Record<string, unknown> {
    return this.config?.options ?? {};
  }

  protected willUpdate(changed: PropertyValues<this>): void {
    if (changed.has("widget")) void this.loadConfig();
  }

  private async loadConfig(): Promise<void> {
    try {
      if (this.widget) {
        this.config = await widgetConfig(this.widget);
        this.brand = this.config.branding;
      } else {
        this.brand = await branding();
      }
      applyTheme(this, this.brand, this.config?.theme);
      await this.load();
    } catch {
      this.failed = true;
    }
  }

  /** Fetch the widget's own data once the configuration is known. */
  protected async load(): Promise<void> {}

  protected status(): unknown {
    if (this.failed) return html`<p role="alert">${t("error")}</p>`;
    return html`<p role="status" class="muted">${t("loading")}</p>`;
  }

  protected footer(): unknown {
    if (!this.brand?.show_powered_by) return nothing;
    return html`<p class="powered muted">
      ${t("poweredBy")}
      <a href="https://tutortrack.app" target="_blank" rel="noopener">TutorTrack</a>
    </p>`;
  }
}
