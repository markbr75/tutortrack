import { css, html, nothing } from "lit";

import { TtWidget } from "./base";
import { api, ApiError, emit } from "./runtime";
import { locale, t } from "./strings";

interface PublicClass {
  id: string;
  name: string;
  course: { id: string; name: string; description: string; subject: string; image_url: string };
  term: string;
  start_date: string;
  weekdays: number[];
  start_time: string;
  location: string;
  online: boolean;
  min_age: number | null;
  max_age: number | null;
  year_groups: string[];
  pricing_label: string;
  price: string;
  places_left: number;
  full: boolean;
  waitlist: boolean;
}
interface Catalogue {
  classes: PublicClass[];
  terms: string;
  payment: string;
}
interface Result {
  status: string;
  pay_url: string;
  student: string;
  waitlist_position: number | null;
}

/** `<tt-class-catalogue>`: public courses and classes with places left, filters (subject,
 * age, day) and online enrolment for new families (E20 FR-20-8 on the E24 runtime). A full
 * class takes waitlist sign-ups; when the organisation takes payment at enrolment the
 * family is sent to the pay page and the place is held meanwhile. */
export class TtClassCatalogue extends TtWidget {
  static properties = {
    ...TtWidget.properties,
    subject: { type: String },
    catalogue: { state: true },
    age: { state: true },
    day: { state: true },
    chosen: { state: true },
    result: { state: true },
    message: { state: true },
    busy: { state: true },
  };

  static styles = [
    TtWidget.baseStyles,
    css`
      .filters,
      form {
        display: grid;
        gap: 12px;
        margin-bottom: 16px;
      }
      @media (min-width: 640px) {
        .filters {
          grid-template-columns: repeat(3, 1fr);
        }
      }
      ul {
        list-style: none;
        padding: 0;
        margin: 0;
        display: grid;
        gap: 12px;
      }
      h3 {
        margin: 0 0 4px;
        font-size: 1.1rem;
      }
      .check {
        display: flex;
        gap: 8px;
        align-items: center;
        font-weight: normal;
      }
      .check input {
        width: auto;
        min-height: auto;
      }
    `,
  ];

  declare subject: string;
  declare catalogue: Catalogue | undefined;
  declare age: string;
  declare day: string;
  declare chosen: PublicClass | undefined;
  declare result: Result | undefined;
  declare message: string;
  declare busy: boolean;

  constructor() {
    super();
    this.subject = "";
    this.age = "";
    this.day = "";
    this.message = "";
    this.busy = false;
  }

  protected async load(): Promise<void> {
    const subject = this.subject || String(this.options.subject ?? "");
    const query = subject ? `?subject=${encodeURIComponent(subject)}` : "";
    const found = await api<Catalogue>(`catalogue${query}`);
    const wanted = (this.options.courses as string[] | undefined) ?? [];
    this.catalogue = {
      ...found,
      classes: wanted.length
        ? found.classes.filter((c) => wanted.includes(c.course.id))
        : found.classes,
    };
  }

  private days(c: PublicClass): string {
    const monday = new Date(Date.UTC(2024, 0, 1));
    return c.weekdays
      .map((d) =>
        new Intl.DateTimeFormat(locale(), { weekday: "long", timeZone: "UTC" }).format(
          new Date(monday.getTime() + d * 86_400_000),
        ),
      )
      .join(", ");
  }

  private visible(): PublicClass[] {
    const all = this.catalogue?.classes ?? [];
    return all.filter((c) => {
      if (this.day !== "" && !c.weekdays.includes(Number(this.day))) return false;
      if (this.age !== "") {
        const age = Number(this.age);
        if (c.min_age !== null && age < c.min_age) return false;
        if (c.max_age !== null && age > c.max_age) return false;
      }
      return true;
    });
  }

  private async enrol(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    if (!this.chosen) return;
    const data = new FormData(event.target as HTMLFormElement);
    this.busy = true;
    this.message = "";
    try {
      const birthday = String(data.get("date_of_birth") ?? "");
      this.result = await api<Result>("enrol", {
        method: "POST",
        body: JSON.stringify({
          group_class: this.chosen.id,
          join_waitlist: this.chosen.full,
          accept_terms: data.get("accept_terms") === "on",
          contact: {
            first_name: data.get("first_name"),
            last_name: data.get("last_name"),
            email: data.get("email"),
            phone: data.get("phone") ?? "",
          },
          student: {
            first_name: data.get("student"),
            date_of_birth: birthday || null,
            year_group: data.get("year_group") ?? "",
          },
        }),
      });
      emit("class_enrolled", { class: this.chosen.id, status: this.result.status });
      if (this.result.pay_url) window.location.assign(this.result.pay_url);
    } catch (error) {
      const detail =
        error instanceof ApiError && error.status === 422
          ? (error.body as { detail?: string } | null)?.detail
          : undefined;
      this.message = detail || t("error");
    } finally {
      this.busy = false;
    }
  }

  render() {
    if (!this.catalogue) return this.status();
    if (this.result) return this.renderResult();
    if (this.chosen) return this.renderForm(this.chosen);
    const classes = this.visible();
    return html`${this.options.show_filters === false ? nothing : this.renderFilters()}
    ${
      classes.length
        ? html`<ul aria-label=${t("classesTitle")}>
            ${classes.map((c) => this.renderCard(c))}
          </ul>`
        : html`<p class="muted">${t("classesNone")}</p>`
    }
    ${this.footer()}`;
  }

  private renderFilters() {
    return html`<div class="filters">
      <div>
        <label for="tt-c-age">${t("classesAge")}</label>
        <input
          id="tt-c-age"
          type="number"
          min="3"
          max="99"
          .value=${this.age}
          @input=${(e: Event) => (this.age = (e.target as HTMLInputElement).value)}
        />
      </div>
      <div>
        <label for="tt-c-day">${t("classesDay")}</label>
        <select
          id="tt-c-day"
          @change=${(e: Event) => (this.day = (e.target as HTMLSelectElement).value)}
        >
          <option value="">${t("classesAnyDay")}</option>
          ${[0, 1, 2, 3, 4, 5, 6].map(
            (d) =>
              html`<option value=${String(d)}>
                ${new Intl.DateTimeFormat(locale(), { weekday: "long", timeZone: "UTC" }).format(
                  new Date(Date.UTC(2024, 0, 1 + d)),
                )}
              </option>`,
          )}
        </select>
      </div>
    </div>`;
  }

  private renderCard(c: PublicClass) {
    const id = `tt-class-${c.id}`;
    return html`<li class="card">
      <article aria-labelledby=${id}>
        <h3 id=${id}>${c.course.name}: ${c.name}</h3>
        ${c.course.description ? html`<p>${c.course.description}</p>` : nothing}
        <p class="muted">
          ${this.days(c)} ${c.start_time} · ${c.term}${c.location ? ` · ${c.location}` : ""}
          ${c.online ? ` · ${t("online")}` : ""}
        </p>
        ${
          this.options.show_prices === false
            ? nothing
            : html`<p>${t("price")}: ${c.price} <span class="muted">(${c.pricing_label})</span></p>`
        }
        <p>${c.full ? t("classesFull") : t("classesPlacesLeft", { n: c.places_left })}</p>
        ${
          c.full && !c.waitlist
            ? nothing
            : html`<button
                class=${c.full ? "secondary" : ""}
                aria-label=${
                  c.full
                    ? t("classesJoinWaitlistFor", { name: c.course.name })
                    : t("classesEnrolIn", { name: c.course.name })
                }
                @click=${() => (this.chosen = c)}
              >
                ${c.full ? t("classesJoinWaitlist") : t("classesEnrol")}
              </button>`
        }
      </article>
    </li>`;
  }

  private renderForm(c: PublicClass) {
    const field = (name: string, label: string, type = "text", required = true) =>
      html`<div>
        <label for="tt-c-${name}">${label}</label>
        <input id="tt-c-${name}" name=${name} type=${type} ?required=${required} />
      </div>`;
    const terms = this.catalogue?.terms ?? "";
    return html`<form @submit=${(e: SubmitEvent) => void this.enrol(e)}>
      <p><strong>${c.course.name}: ${c.name}</strong></p>
      ${field("first_name", t("bookingFirstName"))} ${field("last_name", t("bookingLastName"))}
      ${field("email", t("bookingEmail"), "email")}
      ${field("phone", t("bookingPhone"), "tel", false)} ${field("student", t("bookingStudent"))}
      ${field("date_of_birth", t("classesBirthday"), "date", c.min_age !== null || c.max_age !== null)}
      ${field("year_group", t("classesYearGroup"), "text", c.year_groups.length > 0)}
      ${
        terms
          ? html`<details>
                <summary>${t("classesTerms")}</summary>
                <p>${terms}</p>
              </details>
              <label class="check"
                ><input type="checkbox" name="accept_terms" required />${t("classesAccept")}</label
              >`
          : nothing
      }
      ${this.message ? html`<p role="alert">${this.message}</p>` : nothing}
      <button type="submit" ?disabled=${this.busy}>
        ${c.full ? t("classesJoinWaitlist") : t("classesEnrol")}
      </button>
      <button type="button" class="secondary" @click=${() => (this.chosen = undefined)}>
        ${t("classesBack")}
      </button>
    </form>`;
  }

  private renderResult() {
    const r = this.result as Result;
    const text =
      r.status === "waitlisted"
        ? t("classesWaitlisted", { n: r.waitlist_position ?? "" })
        : r.status === "pending_payment"
          ? t("bookingPay")
          : t("classesEnrolled", { name: r.student });
    return html`<div class="card" role="status">
      <p>${text}</p>
      ${r.pay_url ? html`<a class="button" href=${r.pay_url}>${t("bookingPayNow")}</a>` : nothing}
    </div>`;
  }
}

if (!customElements.get("tt-class-catalogue"))
  customElements.define("tt-class-catalogue", TtClassCatalogue);

declare global {
  interface HTMLElementTagNameMap {
    "tt-class-catalogue": TtClassCatalogue;
  }
}
