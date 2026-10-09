/**
 * i18n for every frontend app. Strings live in locales/<lang>.json; en-US only overrides the
 * en-GB strings that differ. Format money and dates with the helpers below, never by hand.
 */
import i18next, { type i18n as I18n } from "i18next";
import { initReactI18next } from "react-i18next";

import enGB from "./locales/en-GB.json";
import enUS from "./locales/en-US.json";

export const SUPPORTED_LOCALES = ["en-GB", "en-US"] as const;
export type Locale = (typeof SUPPORTED_LOCALES)[number];

export function createI18n(locale: Locale = "en-GB"): I18n {
  const instance = i18next.createInstance();
  void instance.use(initReactI18next).init({
    lng: locale,
    fallbackLng: "en-GB",
    resources: { "en-GB": { translation: enGB }, "en-US": { translation: enUS } },
    interpolation: { escapeValue: false },
    initAsync: false,
  });
  return instance;
}

export interface MoneyValue {
  amount: string;
  currency: string;
}

/** Formats API money ({amount: "12.50", currency: "GBP"}) for display. */
export function formatMoney(value: MoneyValue, locale: string = "en-GB"): string {
  return new Intl.NumberFormat(locale, { style: "currency", currency: value.currency }).format(
    Number(value.amount),
  );
}

/** Formats an ISO datetime in the viewer timezone (or the one given). */
export function formatDateTime(
  iso: string,
  locale: string = "en-GB",
  timeZone?: string,
  options: Intl.DateTimeFormatOptions = { dateStyle: "medium", timeStyle: "short" },
): string {
  return new Intl.DateTimeFormat(locale, { ...options, timeZone }).format(new Date(iso));
}

/** Formats an ISO date (or datetime) as a calendar date, e.g. "9 Oct 2026". */
export function formatDate(iso: string, locale: string = "en-GB"): string {
  // Plain dates are calendar days: format them in UTC so they never shift a day.
  const timeZone = iso.length === 10 ? "UTC" : undefined;
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeZone }).format(new Date(iso));
}

export { I18nextProvider, useTranslation } from "react-i18next";
