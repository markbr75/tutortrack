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

  static baseStyles = css`
    :host {
      display: block;
      font-family: var(--tt-font, system-ui, sans-serif);
      color: var(--tt-text, #111827);
      line-height: 1.5;
    }
    *,
    *::before,
    *::after {
      box-sizing: border-box;
    }
    a {
      color: var(--tt-link-color, #1d4ed8);
    }
    button,
    .button {
      font: inherit;
      display: inline-block;
      min-height: 44px;
      padding: 10px 18px;
      border: 0;
      border-radius: var(--tt-radius, 8px);
      background: var(--tt-brand-color, #1d4ed8);
      color: var(--tt-on-brand, #fff);
      font-weight: 600;
      cursor: pointer;
      text-decoration: none;
    }
    button.secondary {
      background: transparent;
      color: var(--tt-link-color, #1d4ed8);
      border: 1px solid currentColor;
    }
    :focus-visible {
      outline: 3px solid var(--tt-link-color, #1d4ed8);
      outline-offset: 2px;
    }
    input,
    select,
    textarea {
      font: inherit;
      width: 100%;
      min-height: 44px;
      padding: 8px 10px;
      border: 1px solid var(--tt-border, #6b7280);
      border-radius: var(--tt-radius, 8px);
      background: var(--tt-surface, #fff);
      color: inherit;
    }
    label {
      display: block;
      font-weight: 600;
      margin-bottom: 4px;
    }
    .muted {
      color: var(--tt-muted-color, #4b5563);
    }
    .card {
      background: var(--tt-surface, #fff);
      border: 1px solid var(--tt-border, #e5e7eb);
      border-radius: var(--tt-radius, 8px);
      padding: 16px;
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
      margin-top: 12px;
      font-size: 0.8rem;
    }
    [role="alert"] {
      color: #b91c1c;
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
