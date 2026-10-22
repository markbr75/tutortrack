import { css, html, nothing } from "lit";

import { TtWidget } from "./base";
import { api, cached, emit } from "./runtime";
import { t } from "./strings";

interface Tutor {
  slug: string;
  display_name: string;
  headline: string;
  photo_url: string;
  subjects: { subject: string; level: string }[];
  online: boolean;
  in_person: boolean;
  location: string;
}

interface TutorDetail extends Tutor {
  bio: string;
  qualifications: { title: string; institution: string; year: number | null }[];
  languages: string[];
  years_experience: number | null;
}

interface Page {
  results: Tutor[];
  next: string | null;
}

/**
 * `<tt-tutor-directory widget="w-..." enquire-url="/contact">`: searchable public tutor
 * profiles (subject, online/in person, free text) with profile pages and an enquiry button
 * (FR-24-3). Shows only what the organisation approved for publication.
 */
export class TtTutorDirectory extends TtWidget {
  static properties = {
    ...TtWidget.properties,
    enquireUrl: { type: String, attribute: "enquire-url" },
    tutors: { state: true },
    next: { state: true },
    query: { state: true },
    subject: { state: true },
    mode: { state: true },
    selected: { state: true },
    busy: { state: true },
  };

  static styles = [
    TtWidget.baseStyles,
    css`
      form {
        display: grid;
        gap: 12px;
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
        align-items: end;
        margin-bottom: 16px;
      }
      ul.grid {
        list-style: none;
        padding: 0;
        margin: 0;
        display: grid;
        gap: 16px;
        grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
      }
      img {
        width: 80px;
        height: 80px;
        border-radius: 50%;
        object-fit: cover;
      }
      h3 {
        margin: 8px 0 4px;
      }
      /* Subjects read as one line of words, not a cloud of pills. */
      .tags {
        list-style: none;
        padding: 0;
        margin: 8px 0;
        font-weight: 500;
      }
      .tags li {
        display: inline;
      }
      .tags li + li::before {
        content: " · ";
        font-weight: 400;
      }
      .link {
        display: inline;
        background: none;
        border: 0;
        color: inherit;
        padding: 0;
        min-height: 24px;
        text-decoration: underline;
        text-decoration-color: var(--tt-rule);
        font-weight: 600;
        text-align: left;
      }
      .link:hover {
        opacity: 1;
        text-decoration-color: currentColor;
      }
    `,
  ];

  declare enquireUrl: string;
  declare tutors: Tutor[] | undefined;
  declare next: string | null;
  declare query: string;
  declare subject: string;
  declare mode: string;
  declare selected: TutorDetail | undefined;
  declare busy: boolean;

  constructor() {
    super();
    this.enquireUrl = "";
    this.next = null;
    this.query = "";
    this.subject = "";
    this.mode = "";
    this.busy = false;
  }

  private params(cursor = ""): string {
    const p = new URLSearchParams();
    if (this.query) p.set("q", this.query);
    if (this.subject) p.set("subject", this.subject);
    if (this.mode) p.set("online", this.mode === "online" ? "true" : "false");
    const size = Number(this.options.page_size ?? 12);
    p.set("page_size", String(size));
    if (cursor) p.set("cursor", cursor);
    return p.toString();
  }

  protected async load(): Promise<void> {
    await this.search();
  }

  private async search(cursor = ""): Promise<void> {
    this.busy = true;
    try {
      const page = await api<Page>(`tutors?${this.params(cursor)}`);
      const allowed = (this.options.subjects as string[] | undefined) ?? [];
      const rows = allowed.length
        ? page.results.filter((r) =>
            r.subjects.some((s) =>
              allowed.some((a) => a.toLowerCase() === s.subject.toLowerCase()),
            ),
          )
        : page.results;
      this.tutors = cursor ? [...(this.tutors ?? []), ...rows] : rows;
      this.next = page.next ? new URL(page.next, "https://x").searchParams.get("cursor") : null;
      emit("directory_searched", { query: this.query, subject: this.subject });
    } catch {
      this.failed = true;
    } finally {
      this.busy = false;
    }
  }

  private async open(slug: string): Promise<void> {
    try {
      this.selected = await cached<TutorDetail>(`tutors/${encodeURIComponent(slug)}`);
      emit("tutor_viewed", { tutor: slug });
      await this.updateComplete;
      this.renderRoot.querySelector<HTMLElement>("h2")?.focus();
    } catch {
      this.failed = true;
    }
  }

  private subjectsOffered(): string[] {
    const configured = (this.options.subjects as string[] | undefined) ?? [];
    if (configured.length) return configured;
    const seen = new Set<string>();
    for (const tutor of this.tutors ?? []) for (const s of tutor.subjects) seen.add(s.subject);
    return [...seen].sort();
  }

  private enquireHref(name: string): string {
    const form = this.options.enquiry_form as string | undefined;
    const base = this.enquireUrl || (form ? `#enquire-${form}` : "");
    if (!base) return "";
    const sep = base.includes("?") ? "&" : "?";
    return `${base}${sep}tutor=${encodeURIComponent(name)}`;
  }

  private card(tutor: Tutor) {
    return html`<li class="card">
      ${tutor.photo_url ? html`<img src=${tutor.photo_url} alt="" />` : nothing}
      <h3>
        <button
          class="link"
          aria-label=${t("viewProfile", { name: tutor.display_name })}
          @click=${() => this.open(tutor.slug)}
        >
          ${tutor.display_name}
        </button>
      </h3>
      ${tutor.headline ? html`<p class="muted">${tutor.headline}</p>` : nothing}
      <ul class="tags" aria-label=${t("subjects")}>
        ${tutor.subjects
          .slice(0, 4)
          .map((s) => html`<li>${s.subject}${s.level ? ` (${s.level})` : ""}</li>`)}
      </ul>
      <p class="muted">
        ${[tutor.online ? t("online") : "", tutor.in_person ? t("inPerson") : "", tutor.location]
          .filter(Boolean)
          .join(" · ")}
      </p>
    </li>`;
  }

  private detail(tutor: TutorDetail) {
    const enquire = this.enquireHref(tutor.display_name);
    return html`<article class="card">
      <button class="secondary" @click=${() => (this.selected = undefined)}>${t("back")}</button>
      ${tutor.photo_url ? html`<p><img src=${tutor.photo_url} alt="" /></p>` : nothing}
      <h2 tabindex="-1">${tutor.display_name}</h2>
      ${tutor.headline ? html`<p class="muted">${tutor.headline}</p>` : nothing}
      <h3>${t("subjects")}</h3>
      <ul class="tags">
        ${tutor.subjects.map((s) => html`<li>${s.subject}${s.level ? ` (${s.level})` : ""}</li>`)}
      </ul>
      ${
        tutor.bio
          ? html`<h3>${t("about")}</h3>
              ${tutor.bio.split(/\n\n+/).map((p) => html`<p>${p}</p>`)}`
          : nothing
      }
      ${
        tutor.qualifications.length
          ? html`<h3>${t("qualifications")}</h3>
              <ul>
                ${tutor.qualifications.map(
                  (q) =>
                    html`<li>
                      ${q.title}${q.institution ? `, ${q.institution}` : ""}${
                        q.year ? ` (${q.year})` : ""
                      }
                    </li>`,
                )}
              </ul>`
          : nothing
      }
      ${tutor.years_experience ? html`<p>${t("experience", { n: tutor.years_experience })}</p>` : nothing}
      ${
        tutor.languages.length
          ? html`<p>${t("languages")}: ${tutor.languages.join(", ")}</p>`
          : nothing
      }
      ${
        enquire
          ? html`<p>
              <a
                class="button"
                href=${enquire}
                @click=${() => emit("enquiry_started", { tutor: tutor.slug })}
                >${t("enquire", { name: tutor.display_name })}</a
              >
            </p>`
          : nothing
      }
    </article>`;
  }

  render() {
    if (this.selected) return html`${this.detail(this.selected)}${this.footer()}`;
    if (!this.tutors) return this.status();
    const showFilters = this.options.show_filters !== false;
    return html`
      ${
        showFilters
          ? html`<form
              role="search"
              @submit=${(e: Event) => {
                e.preventDefault();
                void this.search();
              }}
            >
              <div>
                <label for="q">${t("search")}</label>
                <input
                  id="q"
                  type="search"
                  .value=${this.query}
                  @input=${(e: Event) => (this.query = (e.target as HTMLInputElement).value)}
                />
              </div>
              <div>
                <label for="subject">${t("subject")}</label>
                <select
                  id="subject"
                  @change=${(e: Event) => {
                    this.subject = (e.target as HTMLSelectElement).value;
                    void this.search();
                  }}
                >
                  <option value="">${t("anySubject")}</option>
                  ${this.subjectsOffered().map(
                    (s) => html`<option value=${s} ?selected=${s === this.subject}>${s}</option>`,
                  )}
                </select>
              </div>
              <div>
                <label for="mode">${t("howTaught")}</label>
                <select
                  id="mode"
                  @change=${(e: Event) => {
                    this.mode = (e.target as HTMLSelectElement).value;
                    void this.search();
                  }}
                >
                  <option value="">${t("anyMode")}</option>
                  <option value="online">${t("online")}</option>
                  <option value="in_person">${t("inPerson")}</option>
                </select>
              </div>
              <div><button type="submit">${t("search")}</button></div>
            </form>`
          : nothing
      }
      <p role="status" class="sr-only">${t("results", { n: this.tutors.length })}</p>
      ${
        this.tutors.length
          ? html`<ul class="grid">
              ${this.tutors.map((tutor) => this.card(tutor))}
            </ul>`
          : html`<p class="muted">${t("noTutors")}</p>`
      }
      ${
        this.next
          ? html`<p>
              <button
                class="secondary"
                ?disabled=${this.busy}
                @click=${() => this.search(this.next ?? "")}
              >
                ${t("more")}
              </button>
            </p>`
          : nothing
      }
      ${this.failed ? html`<p role="alert">${t("error")}</p>` : nothing} ${this.footer()}
    `;
  }
}

if (!customElements.get("tt-tutor-directory")) {
  customElements.define("tt-tutor-directory", TtTutorDirectory);
}

declare global {
  interface HTMLElementTagNameMap {
    "tt-tutor-directory": TtTutorDirectory;
  }
}
