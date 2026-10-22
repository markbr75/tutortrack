import { css, html, nothing, svg } from "lit";

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
        display: flex;
        gap: 2px;
      }
      .stars svg {
        width: 16px;
        height: 16px;
        fill: none;
        stroke: currentColor;
        stroke-width: 1.75;
        stroke-linejoin: round;
      }
      .stars .on {
        fill: currentColor;
      }
      .stars .off {
        color: var(--tt-edge);
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
                        <span class="stars" aria-hidden="true">${stars(r.rating)}</span>
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

/** Five drawn outline stars, the rated number filled (never text glyphs). */
function stars(rating: number) {
  return [1, 2, 3, 4, 5].map(
    (n) =>
      svg`<svg viewBox="0 0 20 20" class=${n <= rating ? "on" : "off"}><path d="M10 2.6l2.3 4.7 5.1.7-3.7 3.6.9 5.1L10 14.3l-4.6 2.4.9-5.1-3.7-3.6 5.1-.7z"/></svg>`,
  );
}

if (!customElements.get("tt-reviews")) customElements.define("tt-reviews", TtReviews);

declare global {
  interface HTMLElementTagNameMap {
    "tt-reviews": TtReviews;
  }
}
