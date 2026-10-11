import { css, html, nothing } from "lit";

import { TtWidget } from "./base";
import { cached } from "./runtime";
import { t } from "./strings";

interface Review {
  id: string;
  quote: string;
  author: string;
  role: string;
  rating: number | null;
  stars: string;
}

/** `<tt-reviews widget="w-..." limit="6">`: testimonials (E25 will add collected reviews). */
export class TtReviews extends TtWidget {
  static properties = {
    ...TtWidget.properties,
    limit: { type: Number },
    reviews: { state: true },
  };

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
      figure,
      blockquote {
        margin: 0;
      }
      .stars {
        color: var(--tt-brand-color, #1d4ed8);
      }
    `,
  ];

  declare limit: number;
  declare reviews: Review[] | undefined;

  constructor() {
    super();
    this.limit = 0;
  }

  protected async load(): Promise<void> {
    const limit = this.limit || Number(this.options.limit ?? 6);
    const min = this.options.min_rating ? `&min_rating=${Number(this.options.min_rating)}` : "";
    this.reviews = await cached<Review[]>(`reviews?limit=${limit}${min}`);
  }

  render() {
    if (!this.reviews) return this.status();
    if (!this.reviews.length) return html`<p class="muted">${t("noReviews")}</p>`;
    return html`<ul>
        ${this.reviews.map(
          (r) =>
            html`<li class="card">
              <figure>
                ${
                  r.rating
                    ? html`<p>
                        <span class="stars" aria-hidden="true">${r.stars}</span>
                        <span class="sr-only">${t("stars", { n: r.rating })}</span>
                      </p>`
                    : nothing
                }
                <blockquote><p>“${r.quote}”</p></blockquote>
                <figcaption class="muted">${r.author}${r.role ? `, ${r.role}` : ""}</figcaption>
              </figure>
            </li>`,
        )}
      </ul>
      ${this.footer()}`;
  }
}

if (!customElements.get("tt-reviews")) customElements.define("tt-reviews", TtReviews);

declare global {
  interface HTMLElementTagNameMap {
    "tt-reviews": TtReviews;
  }
}
