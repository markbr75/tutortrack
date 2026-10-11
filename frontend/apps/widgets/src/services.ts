import { css, html, nothing } from "lit";

import { TtWidget } from "./base";
import { cached } from "./runtime";
import { t } from "./strings";

interface Service {
  id: string;
  name: string;
  description: string;
  subject: string;
  level: string;
  duration_minutes: number;
  price: string;
  pricing_unit_label: string;
}

/** `<tt-services widget="w-...">`: what the organisation teaches, with prices if it chose
 * to show them (prices are formatted by the server in the organisation's locale). */
export class TtServices extends TtWidget {
  static properties = { ...TtWidget.properties, services: { state: true } };

  static styles = [
    TtWidget.baseStyles,
    css`
      ul {
        list-style: none;
        padding: 0;
        margin: 0;
        display: grid;
        gap: 12px;
        grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
      }
      h3 {
        margin: 0 0 4px;
        font-size: 1.05rem;
      }
      .price {
        font-weight: 700;
      }
    `,
  ];

  declare services: Service[] | undefined;

  protected async load(): Promise<void> {
    const query = this.widget ? `?widget=${encodeURIComponent(this.widget)}` : "";
    this.services = await cached<Service[]>(`services${query}`);
  }

  render() {
    if (!this.services) return this.status();
    if (!this.services.length) return html`<p class="muted">${t("noServices")}</p>`;
    return html`<ul>
        ${this.services.map(
          (s) =>
            html`<li class="card">
              <h3>${s.name}</h3>
              ${s.description ? html`<p>${s.description}</p>` : nothing}
              <p class="muted">${t("minutes", { n: s.duration_minutes })}</p>
              <p>
                <span class="sr-only">${t("price")}:</span>
                ${
                  s.price
                    ? html`<span class="price">${s.price}</span>
                        <span class="muted">${s.pricing_unit_label.toLowerCase()}</span>`
                    : html`<span class="muted">${t("askPrice")}</span>`
                }
              </p>
            </li>`,
        )}
      </ul>
      ${this.footer()}`;
  }
}

if (!customElements.get("tt-services")) customElements.define("tt-services", TtServices);

declare global {
  interface HTMLElementTagNameMap {
    "tt-services": TtServices;
  }
}
