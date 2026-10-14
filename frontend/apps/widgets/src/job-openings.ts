import { html, nothing } from "lit";

import { TtWidget } from "./base";
import { referralCode } from "./referral";
import { cached } from "./runtime";
import { t } from "./strings";

interface Opening {
  slug: string;
  title: string;
  location?: string;
  closes_on?: string | null;
}

/** `<tt-job-openings>`: open tutor vacancies (E18) linking to the public vacancy pages
 * (`apply-url="https://.../{slug}"` overrides the link). */
export class TtJobOpenings extends TtWidget {
  static properties = {
    ...TtWidget.properties,
    applyUrl: { type: String, attribute: "apply-url" },
    openings: { state: true },
  };

  static styles = [TtWidget.baseStyles];

  declare applyUrl: string;
  declare openings: Opening[] | undefined;

  constructor() {
    super();
    this.applyUrl = "";
  }

  protected async load(): Promise<void> {
    this.openings = await cached<Opening[]>("job-openings");
  }

  private href(slug: string): string {
    if (this.applyUrl) return this.applyUrl.replace("{slug}", encodeURIComponent(slug));
    const app = (this.brand?.login_url ?? "/login").replace(/\/login$/, "");
    const ref = referralCode(); // E25: a tutor's referral code follows the applicant
    return `${app}/vacancies/${encodeURIComponent(slug)}${ref ? `?ref=${ref}` : ""}`;
  }

  render() {
    if (!this.openings) return this.status();
    if (!this.openings.length) return html`<p class="muted">${t("noVacancies")}</p>`;
    const dates = new Intl.DateTimeFormat(document.documentElement.lang || undefined, {
      dateStyle: "medium",
    });
    return html`<ul>
        ${this.openings.map(
          (o) =>
            html`<li>
              <a href=${this.href(o.slug)} aria-label=${t("apply", { title: o.title })}
                >${o.title}</a
              >
              ${o.location ? html` · <span class="muted">${o.location}</span>` : nothing}
              ${
                o.closes_on
                  ? html` ·
                      <span class="muted"
                        >${t("closes", { date: dates.format(new Date(o.closes_on)) })}</span
                      >`
                  : nothing
              }
            </li>`,
        )}
      </ul>
      ${this.footer()}`;
  }
}

if (!customElements.get("tt-job-openings")) customElements.define("tt-job-openings", TtJobOpenings);

declare global {
  interface HTMLElementTagNameMap {
    "tt-job-openings": TtJobOpenings;
  }
}
