/**
 * Referral and affiliate attribution (E25 FR-25-2/3). A visit with `?ref=CODE` is counted
 * (`POST /public/ref`) and the code remembered so a later enquiry or tutor application
 * carries it (`utm.ref`). The code is kept for the browser session; it is kept for the
 * organisation's attribution window (a `tt_ref` cookie) only with marketing consent.
 */
import { readChoice } from "./cookie-consent";
import { api } from "./runtime";

const KEY = "tt_ref";
const CODE = /^[A-Za-z0-9]{4,20}$/;

interface RefResult {
  valid: boolean;
  kind: string;
  landing_path: string;
  remember_days: number;
  offer: string;
}

function fromCookie(): string {
  const raw = document.cookie
    .split("; ")
    .find((c) => c.startsWith(`${KEY}=`))
    ?.slice(KEY.length + 1);
  return raw && CODE.test(raw) ? raw : "";
}

function fromSession(): string {
  try {
    const value = window.sessionStorage.getItem(KEY) ?? "";
    return CODE.test(value) ? value : "";
  } catch {
    return "";
  }
}

/** The code this visitor arrived with (this page's URL, the session, or the cookie). */
export function referralCode(): string {
  const param = new URLSearchParams(window.location.search).get("ref") ?? "";
  if (CODE.test(param)) return param.toUpperCase();
  return (fromSession() || fromCookie()).toUpperCase();
}

/** Count the visit and remember the code (once per page load). */
export async function captureReferral(): Promise<RefResult | null> {
  const param = new URLSearchParams(window.location.search).get("ref") ?? "";
  if (!CODE.test(param)) return null;
  const code = param.toUpperCase();
  try {
    window.sessionStorage.setItem(KEY, code);
  } catch {
    // private mode: the URL still carries the code on this page
  }
  let result: RefResult;
  try {
    result = await api<RefResult>("ref", { method: "POST", body: JSON.stringify({ code }) });
  } catch {
    return null;
  }
  if (result.valid && result.remember_days > 0 && readChoice()?.marketing) {
    const maxAge = result.remember_days * 86_400;
    document.cookie = `${KEY}=${code}; max-age=${maxAge}; path=/; SameSite=Lax`;
  }
  return result;
}
