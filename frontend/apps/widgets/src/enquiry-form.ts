import { css, html, nothing } from "lit";

import { TtWidget } from "./base";
import { referralCode } from "./referral";
import { api, ApiError, emit } from "./runtime";
import { t } from "./strings";

interface Field {
  key: string;
  label: string;
  type: string;
  required?: boolean;
  options?: string[];
  help?: string;
  show_if?: { field: string; equals: unknown };
}

interface PublicForm {
  name: string;
  schema: { steps: { title?: string; fields: Field[] }[] };
  thank_you: string;
  redirect_url: string;
  consent_text: string;
  turnstile_site_key: string;
}

declare global {
  interface Window {
    turnstile?: {
      render: (el: HTMLElement, opts: { sitekey: string; callback: (t: string) => void }) => void;
    };
  }
}

const INPUT_TYPES: Record<string, string> = {
  email: "email",
  phone: "tel",
  number: "number",
  date: "date",
  postcode: "text",
  text: "text",
};

/**
 * `<tt-enquiry-form form="enquire">`: one of the organisation's E17 enquiry forms. Posts to
 * the public form endpoint (CAPTCHA + honeypot + rate limit) and emits
 * `tt:enquiry_submitted` for GA4/Meta pixel hooks.
 */
export class TtEnquiryForm extends TtWidget {
  static properties = {
    ...TtWidget.properties,
    form: { type: String },
    definition: { state: true },
    answers: { state: true },
    errors: { state: true },
    sent: { state: true },
    sending: { state: true },
  };

  static styles = [
    TtWidget.baseStyles,
    css`
      fieldset {
        border: 0;
        padding: 0;
        margin: 0 0 16px;
      }
      legend {
        font-weight: 700;
        font-size: 1.1rem;
        margin-bottom: 8px;
      }
      .field {
        margin-bottom: 14px;
      }
      .check {
        display: flex;
        gap: 8px;
        align-items: flex-start;
        font-weight: 400;
      }
      .check input {
        width: auto;
        min-height: 24px;
      }
      .hp {
        position: absolute;
        left: -9999px;
      }
      .error {
        color: #b91c1c;
        font-size: 0.9rem;
        margin: 4px 0 0;
      }
    `,
  ];

  declare form: string;
  declare definition: PublicForm | undefined;
  declare answers: Record<string, unknown>;
  declare errors: Record<string, string[]>;
  declare sent: boolean;
  declare sending: boolean;
  private token = "";
  private honeypot = "";

  constructor() {
    super();
    this.form = "";
    this.answers = {};
    this.errors = {};
    this.sent = false;
    this.sending = false;
  }

  private get slug(): string {
    return this.form || String(this.options.form ?? "");
  }

  protected async load(): Promise<void> {
    if (!this.slug) {
      this.failed = true;
      return;
    }
    this.definition = await api<PublicForm>(`forms/${encodeURIComponent(this.slug)}`);
    const tutor = new URLSearchParams(window.location.search).get("tutor");
    if (tutor) this.answers = { ...this.answers, notes: tutor };
    if (this.definition.turnstile_site_key) await this.captcha(this.definition.turnstile_site_key);
  }

  private async captcha(siteKey: string): Promise<void> {
    if (!window.turnstile) {
      await new Promise<void>((resolve) => {
        const s = document.createElement("script");
        s.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit";
        s.async = true;
        s.onload = () => resolve();
        s.onerror = () => resolve();
        document.head.append(s);
      });
    }
    await this.updateComplete;
    const slot = this.renderRoot.querySelector<HTMLElement>(".captcha");
    if (slot && window.turnstile) {
      window.turnstile.render(slot, { sitekey: siteKey, callback: (tok) => (this.token = tok) });
    }
  }

  private set(key: string, value: unknown): void {
    this.answers = { ...this.answers, [key]: value };
  }

  private async submit(e: Event): Promise<void> {
    e.preventDefault();
    this.sending = true;
    this.errors = {};
    const params = new URLSearchParams(window.location.search);
    const utm = Object.fromEntries(
      [...params.entries()].filter(
        ([k]) => k.startsWith("utm_") || k === "gclid" || k === "fbclid",
      ),
    );
    try {
      await api(`forms/${encodeURIComponent(this.slug)}`, {
        method: "POST",
        body: JSON.stringify({
          data: this.answers,
          utm: {
            ...utm,
            referrer: document.referrer,
            landing_page: window.location.href,
            ...(referralCode() ? { ref: referralCode() } : {}),
          },
          captcha_token: this.token,
          website: this.honeypot,
        }),
      });
      this.sent = true;
      emit("enquiry_submitted", { form: this.slug });
      if (this.definition?.redirect_url) window.location.assign(this.definition.redirect_url);
      await this.updateComplete;
      this.renderRoot.querySelector<HTMLElement>("[role=status]")?.focus();
    } catch (error) {
      const body =
        error instanceof ApiError ? (error.body as { errors?: Record<string, string[]> }) : null;
      this.errors = body?.errors ?? { _: [t("error")] };
      await this.updateComplete;
      this.renderRoot.querySelector<HTMLElement>("[aria-invalid=true], .summary")?.focus();
    } finally {
      this.sending = false;
    }
  }

  private visible(field: Field): boolean {
    return !field.show_if || this.answers[field.show_if.field] === field.show_if.equals;
  }

  private control(field: Field) {
    const id = `f-${field.key}`;
    const error = this.errors[field.key]?.[0];
    const describedBy = error ? `${id}-error` : field.help ? `${id}-help` : "";
    const value = this.answers[field.key];
    const common = {
      id,
      invalid: error ? "true" : "false",
    };
    let input: unknown;
    if (field.type === "textarea") {
      input = html`<textarea
        id=${common.id}
        rows="4"
        ?required=${field.required}
        aria-invalid=${common.invalid}
        aria-describedby=${describedBy || nothing}
        .value=${String(value ?? "")}
        @input=${(e: Event) => this.set(field.key, (e.target as HTMLTextAreaElement).value)}
      ></textarea>`;
    } else if (field.type === "select") {
      input = html`<select
        id=${common.id}
        ?required=${field.required}
        aria-invalid=${common.invalid}
        aria-describedby=${describedBy || nothing}
        @change=${(e: Event) => this.set(field.key, (e.target as HTMLSelectElement).value)}
      >
        <option value=""></option>
        ${(field.options ?? []).map((o) => html`<option value=${o}>${o}</option>`)}
      </select>`;
    } else if (field.type === "checkbox" || field.type === "consent") {
      return html`<div class="field">
        <label class="check">
          <input
            type="checkbox"
            ?required=${field.required}
            aria-invalid=${common.invalid}
            @change=${(e: Event) => this.set(field.key, (e.target as HTMLInputElement).checked)}
          />
          <span>${field.label}</span>
        </label>
        ${error ? html`<p class="error" id="${id}-error">${error}</p>` : nothing}
      </div>`;
    } else if (field.type === "students") {
      const students = (value as { first_name: string; subjects: string }[] | undefined) ?? [
        { first_name: "", subjects: "" },
      ];
      const change = (i: number, patch: Record<string, string>) =>
        this.set(
          field.key,
          students.map((s, j) => (j === i ? { ...s, ...patch } : s)),
        );
      return html`<fieldset class="field">
        <legend>${field.label}</legend>
        ${students.map(
          (s, i) =>
            html`<div class="field">
                <label for="${id}-${i}">${t("student", { n: i + 1 })}</label>
                <input
                  id="${id}-${i}"
                  ?required=${field.required && i === 0}
                  .value=${s.first_name}
                  @input=${(e: Event) => change(i, { first_name: (e.target as HTMLInputElement).value })}
                />
              </div>
              <div class="field">
                <label for="${id}-${i}-s">${t("studentSubjects", { n: i + 1 })}</label>
                <input
                  id="${id}-${i}-s"
                  .value=${s.subjects}
                  @input=${(e: Event) => change(i, { subjects: (e.target as HTMLInputElement).value })}
                />
              </div>`,
        )}
        <button
          type="button"
          class="secondary"
          @click=${() => this.set(field.key, [...students, { first_name: "", subjects: "" }])}
        >
          ${t("addStudent")}
        </button>
        ${error ? html`<p class="error" id="${id}-error">${error}</p>` : nothing}
      </fieldset>`;
    } else {
      input = html`<input
        id=${common.id}
        type=${INPUT_TYPES[field.type] ?? "text"}
        autocomplete=${field.type === "email" ? "email" : field.type === "phone" ? "tel" : nothing}
        ?required=${field.required}
        aria-invalid=${common.invalid}
        aria-describedby=${describedBy || nothing}
        .value=${String(value ?? "")}
        @input=${(e: Event) => this.set(field.key, (e.target as HTMLInputElement).value)}
      />`;
    }
    return html`<div class="field">
      <label for=${id}>
        ${field.label}${field.required ? html` <span class="muted">(${t("required")})</span>` : nothing}
      </label>
      ${input}
      ${field.help && !error ? html`<p class="muted" id="${id}-help">${field.help}</p>` : nothing}
      ${error ? html`<p class="error" id="${id}-error">${error}</p>` : nothing}
    </div>`;
  }

  render() {
    const form = this.definition;
    if (!form) return this.status();
    if (this.sent) {
      return html`<p role="status" tabindex="-1">${form.thank_you || t("thanks")}</p>
        ${this.footer()}`;
    }
    const general = this.errors._?.[0] ?? (Object.keys(this.errors).length ? t("fixErrors") : "");
    return html`<form @submit=${(e: Event) => this.submit(e)} novalidate>
        ${general ? html`<p role="alert" class="summary" tabindex="-1">${general}</p>` : nothing}
        ${form.schema.steps.map(
          (step) =>
            html`<fieldset>
              ${step.title ? html`<legend>${step.title}</legend>` : nothing}
              ${step.fields.filter((f) => this.visible(f)).map((f) => this.control(f))}
            </fieldset>`,
        )}
        <div class="hp" aria-hidden="true">
          <label for="hp-website">${t("website")}</label>
          <input
            id="hp-website"
            tabindex="-1"
            autocomplete="off"
            @input=${(e: Event) => (this.honeypot = (e.target as HTMLInputElement).value)}
          />
        </div>
        ${form.consent_text ? html`<p class="muted">${form.consent_text}</p>` : nothing}
        <div class="captcha"></div>
        <button type="submit" ?disabled=${this.sending}>
          ${this.sending ? t("sending") : t("send")}
        </button>
      </form>
      ${this.footer()}`;
  }
}

if (!customElements.get("tt-enquiry-form")) {
  customElements.define("tt-enquiry-form", TtEnquiryForm);
}

declare global {
  interface HTMLElementTagNameMap {
    "tt-enquiry-form": TtEnquiryForm;
  }
}
