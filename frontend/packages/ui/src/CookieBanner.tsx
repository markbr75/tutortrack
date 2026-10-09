import { useEffect, useState } from "react";

import { Button } from "./Button";

/**
 * Cookie consent (E29 FR-29-3): necessary / analytics / marketing. "Reject non-essential"
 * is as prominent as "Accept all" and nothing optional loads until the visitor chooses.
 * The choice is stored in the `tt_consent` cookie (180 days) shared with the widgets.
 */
export interface CookieChoice {
  necessary: true;
  analytics: boolean;
  marketing: boolean;
  version: number;
}

export const COOKIE_CONSENT_VERSION = 1;
const COOKIE = "tt_consent";

export function readCookieConsent(): CookieChoice | null {
  if (typeof document === "undefined") return null;
  const raw = document.cookie
    .split("; ")
    .find((c) => c.startsWith(`${COOKIE}=`))
    ?.slice(COOKIE.length + 1);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(decodeURIComponent(raw)) as CookieChoice;
    return parsed.version === COOKIE_CONSENT_VERSION ? parsed : null;
  } catch {
    return null;
  }
}

export function writeCookieConsent(choice: Omit<CookieChoice, "necessary" | "version">) {
  const value: CookieChoice = { necessary: true, version: COOKIE_CONSENT_VERSION, ...choice };
  document.cookie = `${COOKIE}=${encodeURIComponent(JSON.stringify(value))}; Max-Age=${
    180 * 24 * 3600
  }; Path=/; SameSite=Lax`;
  window.dispatchEvent(new CustomEvent("tt-cookie-consent", { detail: value }));
  return value;
}

export interface CookieBannerLabels {
  title: string;
  body: string;
  acceptAll: string;
  rejectAll: string;
  customise: string;
  save: string;
  analytics: string;
  marketing: string;
  necessary: string;
}

export function CookieBanner({ labels }: { labels: CookieBannerLabels }) {
  const [open, setOpen] = useState(false);
  const [custom, setCustom] = useState(false);
  const [analytics, setAnalytics] = useState(false);
  const [marketing, setMarketing] = useState(false);

  useEffect(() => setOpen(readCookieConsent() === null), []);
  if (!open) return null;

  const choose = (a: boolean, m: boolean) => {
    writeCookieConsent({ analytics: a, marketing: m });
    setOpen(false);
  };

  return (
    <section
      role="region"
      aria-label={labels.title}
      className="fixed inset-x-0 bottom-0 z-50 border-t border-border bg-background p-4 shadow-lg"
    >
      <div className="mx-auto flex max-w-4xl flex-col gap-3">
        <h2 className="font-medium">{labels.title}</h2>
        <p className="text-sm">{labels.body}</p>
        {custom ? (
          <fieldset className="flex flex-wrap gap-4 text-sm">
            <legend className="sr-only">{labels.customise}</legend>
            <label className="flex items-center gap-2">
              <input type="checkbox" checked disabled /> {labels.necessary}
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={analytics}
                onChange={(e) => setAnalytics(e.target.checked)}
              />
              {labels.analytics}
            </label>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={marketing}
                onChange={(e) => setMarketing(e.target.checked)}
              />
              {labels.marketing}
            </label>
          </fieldset>
        ) : null}
        <div className="flex flex-wrap gap-2">
          {/* Equal prominence for accepting and rejecting. */}
          <Button onClick={() => choose(true, true)}>{labels.acceptAll}</Button>
          <Button onClick={() => choose(false, false)}>{labels.rejectAll}</Button>
          {custom ? (
            <Button variant="secondary" onClick={() => choose(analytics, marketing)}>
              {labels.save}
            </Button>
          ) : (
            <Button variant="secondary" onClick={() => setCustom(true)}>
              {labels.customise}
            </Button>
          )}
        </div>
      </div>
    </section>
  );
}
