import { css, html, nothing } from "lit";

import { TtWidget } from "./base";
import { api, ApiError, cached, emit } from "./runtime";
import { locale, t } from "./strings";

interface Money {
  amount: string;
  currency: string;
}
interface Service {
  id: string;
  name: string;
  description: string;
  duration_minutes: number;
  price: Money | null;
  tutors: { id: string; name: string }[];
}
interface Slot {
  tutor: string;
  tutor_name: string;
  start: string;
  end: string;
}
interface Booking {
  id: string;
  status: string;
  start: string;
  tutor_name: string;
  service_name: string;
  expires_at: string;
  quote: { amount: Money } | null;
  token?: string;
}

function isoDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** `<tt-booking widget="w-...">`: online self-booking for new families (E08-T14 / E24):
 * service → tutor or any → free time → their details → book (and pay when the organisation
 * takes payment at booking). The slot is held for a few minutes while they finish. */
export class TtBooking extends TtWidget {
  static properties = {
    ...TtWidget.properties,
    services: { state: true },
    slots: { state: true },
    service: { state: true },
    booking: { state: true },
    payUrl: { state: true },
    message: { state: true },
    busy: { state: true },
  };

  static styles = [
    TtWidget.baseStyles,
    css`
      form,
      .grid {
        display: grid;
        gap: 12px;
      }
      ul {
        list-style: none;
        padding: 0;
        margin: 0;
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
      }
    `,
  ];

  declare services: Service[] | undefined;
  declare slots: Slot[] | undefined;
  declare service: Service | undefined;
  declare booking: Booking | undefined;
  declare payUrl: string;
  declare message: string;
  declare busy: boolean;
  private tutor = "";
  private chosenSlot: Slot | undefined;

  constructor() {
    super();
    this.payUrl = "";
    this.message = "";
    this.busy = false;
  }

  protected async load(): Promise<void> {
    const all = await cached<Service[]>("booking/services");
    const wanted = (this.options.services as string[] | undefined) ?? [];
    this.services = wanted.length ? all.filter((s) => wanted.includes(s.id)) : all;
    if (this.options.tutor) this.tutor = String(this.options.tutor);
  }

  private format(value: string): string {
    return new Intl.DateTimeFormat(locale(), {
      weekday: "short",
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(value));
  }

  private money(value: Money | null | undefined): string {
    if (!value) return "";
    return new Intl.NumberFormat(locale(), { style: "currency", currency: value.currency }).format(
      Number(value.amount),
    );
  }

  private async pick(service: Service): Promise<void> {
    this.service = service;
    this.slots = undefined;
    const days = Number(this.options.days ?? this.getAttribute("days") ?? 7);
    const from = new Date();
    const to = new Date(from.getTime() + (days - 1) * 86_400_000);
    const tutor = this.tutor ? `&tutor=${encodeURIComponent(this.tutor)}` : "";
    this.slots = await api<Slot[]>(
      `booking/slots?service=${service.id}&from=${isoDate(from)}&to=${isoDate(to)}${tutor}`,
    );
  }

  private async hold(event: SubmitEvent): Promise<void> {
    event.preventDefault();
    if (!this.service || !this.chosenSlot) return;
    const data = new FormData(event.target as HTMLFormElement);
    this.busy = true;
    this.message = "";
    try {
      this.booking = await api<Booking>("booking/holds", {
        method: "POST",
        body: JSON.stringify({
          service: this.service.id,
          tutor: this.chosenSlot.tutor,
          start: this.chosenSlot.start,
          promo_code: data.get("promo") ?? "",
          contact: {
            first_name: data.get("first_name"),
            last_name: data.get("last_name"),
            email: data.get("email"),
            phone: data.get("phone") ?? "",
            student_first_name: data.get("student"),
          },
        }),
      });
      emit("booking_held", { service: this.service.id });
    } catch (error) {
      this.message =
        error instanceof ApiError && error.status === 422 ? t("bookingTaken") : t("error");
    } finally {
      this.busy = false;
    }
  }

  private async submit(): Promise<void> {
    if (!this.booking?.token) return;
    this.busy = true;
    try {
      const token = encodeURIComponent(this.booking.token);
      const result = await api<{ booking: Booking; pay_url: string }>(
        `booking/holds/${this.booking.id}/submit?token=${token}`,
        { method: "POST" },
      );
      this.booking = { ...result.booking, token: this.booking.token };
      this.payUrl = result.pay_url;
      emit("booking_submitted", { status: result.booking.status });
    } catch {
      this.message = t("bookingExpired");
    } finally {
      this.busy = false;
    }
  }

  render() {
    if (!this.services) return this.status();
    if (!this.services.length) return html`<p class="muted">${t("noServices")}</p>`;
    if (this.booking) return this.renderBooking();
    return html`<div class="grid">
        <label for="tt-service">${t("bookingService")}</label>
        <select
          id="tt-service"
          @change=${(e: Event) => {
            const id = (e.target as HTMLSelectElement).value;
            const found = this.services?.find((s) => s.id === id);
            if (found) void this.pick(found);
          }}
        >
          <option value="">${t("bookingChoose")}</option>
          ${this.services.map(
            (s) =>
              html`<option value=${s.id}>
                ${s.name}${s.price && this.options.show_prices !== false ? ` · ${this.money(s.price)}` : ""}
              </option>`,
          )}
        </select>
        ${this.service ? this.renderSlots() : nothing}
        ${this.chosenSlot ? this.renderDetails() : nothing}
        ${this.message ? html`<p role="alert">${this.message}</p>` : nothing}
      </div>
      ${this.footer()}`;
  }

  private renderSlots() {
    if (!this.slots) return html`<p role="status" class="muted">${t("loading")}</p>`;
    if (!this.slots.length) return html`<p class="muted">${t("bookingNoTimes")}</p>`;
    return html`<fieldset>
      <legend>${t("bookingTimes")}</legend>
      <ul>
        ${this.slots.map(
          (slot) =>
            html`<li>
              <button
                class=${slot === this.chosenSlot ? "" : "secondary"}
                aria-pressed=${slot === this.chosenSlot}
                @click=${() => {
                  this.chosenSlot = slot;
                  this.requestUpdate();
                }}
              >
                ${this.format(slot.start)} · ${slot.tutor_name}
              </button>
            </li>`,
        )}
      </ul>
    </fieldset>`;
  }

  private renderDetails() {
    const field = (name: string, label: string, type = "text", required = true) =>
      html`<div>
        <label for="tt-b-${name}">${label}</label>
        <input id="tt-b-${name}" name=${name} type=${type} ?required=${required} />
      </div>`;
    return html`<form @submit=${(e: SubmitEvent) => void this.hold(e)}>
      ${field("first_name", t("bookingFirstName"))} ${field("last_name", t("bookingLastName"))}
      ${field("email", t("bookingEmail"), "email")}
      ${field("phone", t("bookingPhone"), "tel", false)} ${field("student", t("bookingStudent"))}
      ${field("promo", t("bookingPromo"), "text", false)}
      <button type="submit" ?disabled=${this.busy}>${t("bookingContinue")}</button>
    </form>`;
  }

  private renderBooking() {
    const b = this.booking as Booking;
    if (b.status === "held") {
      return html`<div class="card" aria-live="polite">
        <p><strong>${b.service_name}</strong> · ${this.format(b.start)} · ${b.tutor_name}</p>
        ${b.quote ? html`<p>${t("price")}: ${this.money(b.quote.amount)}</p>` : nothing}
        <p class="muted">${t("bookingHeld", { time: this.format(b.expires_at) })}</p>
        <button ?disabled=${this.busy} @click=${() => void this.submit()}>
          ${t("bookingBook")}
        </button>
        ${this.message ? html`<p role="alert">${this.message}</p>` : nothing}
      </div>`;
    }
    return html`<div class="card" role="status">
      <p>
        ${b.status === "confirmed" ? t("bookingConfirmed") : b.status === "awaiting_payment" ? t("bookingPay") : t("bookingRequested")}
      </p>
      ${this.payUrl ? html`<a class="button" href=${this.payUrl}>${t("bookingPayNow")}</a>` : nothing}
    </div>`;
  }
}

if (!customElements.get("tt-booking")) customElements.define("tt-booking", TtBooking);

declare global {
  interface HTMLElementTagNameMap {
    "tt-booking": TtBooking;
  }
}
