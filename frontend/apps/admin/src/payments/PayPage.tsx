import { ApiError, unwrap } from "@tutortrack/api-client";
import { formatDate, formatMoney, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, Spinner } from "@tutortrack/ui";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api } from "../api";
import { stripeFor, type StripeClient, type StripeElements } from "./stripe";

interface Mounted {
  stripe: StripeClient;
  elements: StripeElements;
  intent: string;
}

type Provider = "stripe" | "gocardless" | "paypal";

/** One phone-first column for the public pay and setup pages. */
const PAGE = "mx-auto max-w-lg space-y-6 px-4 py-8 sm:px-6";

/** The business the family is paying, as a ruled brand line above the page heading: the
 * tenant's logo when it has one, otherwise its name in ink. Never a faded kicker. */
function BrandLine({ name }: { name: string }) {
  const brand = useQuery({
    queryKey: ["public-branding"],
    queryFn: async () => unwrap(await api.GET("/api/v1/public/branding")),
    staleTime: 10 * 60_000,
    retry: false,
  });
  const logo = brand.data?.logo_url;
  const dark = brand.data?.logo_dark_url;
  return (
    <div className="mb-5 border-b border-border pb-4">
      {logo ? (
        <picture>
          {dark ? <source srcSet={dark} media="(prefers-color-scheme: dark)" /> : null}
          <img src={logo} alt={name} className="h-8 w-auto" />
        </picture>
      ) : (
        <p className="text-base font-semibold">{name}</p>
      )}
    </div>
  );
}

/** What a provider added to our URL when the customer came back from its pages:
 * GoCardless ``intent``, PayPal ``token`` or Stripe ``payment_intent``. */
function returned(): { provider: Provider; intent: string } | null {
  const params = new URLSearchParams(window.location.search);
  const provider = params.get("provider");
  const intent = params.get("intent") ?? params.get("token");
  if ((provider === "gocardless" || provider === "paypal") && intent) return { provider, intent };
  const stripe = params.get("payment_intent");
  return stripe ? { provider: "stripe", intent: stripe } : null;
}

function problemMessage(error: unknown, fallback: string): string {
  return error instanceof ApiError || error instanceof Error ? error.message : fallback;
}

/** Mounts Stripe's Payment Element into a container once a client secret exists. */
function usePaymentElement(setup: { key: string; account: string; secret: string } | null) {
  const ref = useRef<HTMLDivElement>(null);
  const [mounted, setMounted] = useState<Omit<Mounted, "intent"> | null>(null);
  const [error, setError] = useState("");
  const key = setup?.key ?? "";
  const account = setup?.account ?? "";
  const secret = setup?.secret ?? "";
  useEffect(() => {
    if (!secret || !ref.current) return;
    let element: { destroy: () => void } | null = null;
    let cancelled = false;
    stripeFor(key, account)
      .then((stripe) => {
        if (cancelled || !ref.current) return;
        const elements = stripe.elements({ clientSecret: secret });
        const created = elements.create("payment");
        created.mount(ref.current);
        element = created;
        setMounted({ stripe, elements });
      })
      .catch((e: Error) => setError(e.message));
    return () => {
      cancelled = true;
      element?.destroy();
    };
  }, [key, account, secret]);
  return { ref, mounted, error };
}

function ProviderChoice({
  providers,
  value,
  onChange,
  legend,
}: {
  providers: string[];
  value: string;
  onChange: (provider: Provider) => void;
  legend: string;
}) {
  const { t } = useTranslation();
  if (providers.length < 2) return null;
  return (
    <fieldset>
      <legend className="mb-2 text-sm font-medium">{legend}</legend>
      <div className="divide-y divide-rule rounded-md border border-field">
        {providers.map((p) => (
          <label key={p} className="flex min-h-11 cursor-pointer items-center gap-3 px-3 text-sm">
            <input
              type="radio"
              name="provider"
              className="size-4"
              checked={value === p}
              onChange={() => onChange(p as Provider)}
            />
            {t(`payOptions.${p}`)}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

/** The hosted pay page for an invoice or payment request (FR-11-4): card details in
 * Stripe's own fields, or a bank payment (GoCardless) or PayPal on their own pages. */
export function PayPage({ token }: { token: string }) {
  const { t, i18n } = useTranslation();
  const [saveMethod, setSaveMethod] = useState(false);
  const [chosen, setChosen] = useState<Provider | "">("");
  const [paid, setPaid] = useState(false);
  const [message, setMessage] = useState("");
  const page = useQuery({
    queryKey: ["pay", token],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/pay/{token}", { params: { path: { token } } })),
  });
  const providers = (page.data?.providers ?? []) as Provider[];
  const provider: Provider = chosen || providers[0] || "stripe";
  const intent = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/pay/{token}/intent", {
          params: { path: { token } },
          body: { save_method: provider === "stripe" && saveMethod, provider },
        }),
      ),
    onSuccess: (data) => {
      if (data.redirect_url) window.location.assign(data.redirect_url);
    },
  });
  const setup =
    intent.data && !intent.data.redirect_url
      ? {
          key: intent.data.publishable_key,
          account: intent.data.account,
          secret: intent.data.client_secret,
        }
      : null;
  const element = usePaymentElement(setup);
  const confirm = useMutation({
    mutationFn: async ({ id, via }: { id: string; via: Provider }) =>
      unwrap(
        await api.POST("/api/v1/pay/{token}/confirm", {
          params: { path: { token } },
          body: { intent: id, provider: via },
        }),
      ),
    onSuccess: (result) => {
      if (result.status === "succeeded") setPaid(true);
      else setMessage(t("pay.processing"));
    },
  });

  // Back from a provider's page (3-D Secure, GoCardless or PayPal).
  useEffect(() => {
    const back = returned();
    if (back) confirm.mutate({ id: back.intent, via: back.provider });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once, on arrival
  }, []);

  const pay = async () => {
    if (!element.mounted || !intent.data) return;
    setMessage("");
    const result = await element.mounted.stripe.confirmPayment({
      elements: element.mounted.elements,
      redirect: "if_required",
      confirmParams: { return_url: window.location.href },
    });
    if (result.error) setMessage(result.error.message ?? t("pay.failed"));
    else confirm.mutate({ id: result.paymentIntent?.id ?? intent.data.intent, via: "stripe" });
  };

  if (page.isPending)
    return (
      <main className={PAGE}>
        <Spinner label={t("grid.loading")} />
      </main>
    );
  if (!page.data)
    return (
      <main className={PAGE}>
        <Alert tone="danger">{t("pay.notFound")}</Alert>
      </main>
    );
  const data = page.data;
  const money = (value: { amount: string; currency: string }) => formatMoney(value, i18n.language);
  const due = Number(data.amount_due.amount);
  const choosing = !intent.data || Boolean(intent.data.redirect_url);

  return (
    <main className={PAGE}>
      <header>
        <BrandLine name={data.organisation} />
        <h1 className="text-xl font-semibold">
          {data.kind === "invoice"
            ? t("pay.invoiceTitle", { number: data.number })
            : t("pay.requestTitle", { number: data.number })}
        </h1>
        <p className="mt-1 text-sm text-muted-foreground tabular-nums">
          {data.client_name}
          {data.due_date
            ? ` · ${t("pay.dueOn", { date: formatDate(data.due_date, i18n.language) })}`
            : ""}
        </p>
      </header>
      <section
        aria-label={t("billing.lines")}
        className="rounded-xl border border-border bg-surface text-sm"
      >
        <ul>
          {data.lines.map((line, i) => (
            <li
              key={i}
              className="flex justify-between gap-4 border-t border-rule px-5 py-2.5 first:border-0"
            >
              <span className="min-w-0">{line.description}</span>
              <span className="w-28 shrink-0 text-right tabular-nums">{money(line.amount)}</span>
            </li>
          ))}
        </ul>
        <p className="flex justify-between gap-4 border-t border-border px-5 py-3 text-base font-semibold">
          <span>{t("pay.amountDue")}</span>
          <span className="w-28 shrink-0 text-right tabular-nums">{money(data.amount_due)}</span>
        </p>
        {data.has_pdf ? (
          <p className="border-t border-rule px-5 py-3">
            <a
              className="font-medium text-link underline-offset-2 hover:underline"
              href={`/api/v1/pay/${token}/pdf`}
              target="_blank"
              rel="noreferrer"
            >
              {t("pay.downloadPdf")}
            </a>
          </p>
        ) : null}
      </section>
      {paid || due === 0 ? (
        <Alert tone="success">{paid ? t("pay.thanks") : t("pay.nothingDue")}</Alert>
      ) : !data.can_pay_online ? (
        <Alert>{t("pay.offline")}</Alert>
      ) : (
        <section
          aria-label={t("pay.payOnline")}
          className="space-y-4 rounded-xl border border-border bg-surface p-5"
        >
          {choosing ? (
            <>
              <ProviderChoice
                providers={providers}
                value={provider}
                onChange={setChosen}
                legend={t("payOptions.payWith")}
              />
              {provider === "stripe" ? (
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    className="size-4"
                    checked={saveMethod}
                    onChange={(e) => setSaveMethod(e.target.checked)}
                  />
                  {t("pay.saveMethod")}
                </label>
              ) : (
                <p className="text-sm text-muted-foreground">{t(`payOptions.${provider}Help`)}</p>
              )}
              <Button
                className="w-full"
                onClick={() => intent.mutate()}
                disabled={intent.isPending}
              >
                {t("pay.payAmount", { amount: money(data.amount_due) })}
              </Button>
            </>
          ) : (
            <>
              <div ref={element.ref} />
              <Button
                className="w-full"
                onClick={() => void pay()}
                disabled={!element.mounted || confirm.isPending}
              >
                {t("pay.payNow")}
              </Button>
            </>
          )}
          {intent.error || element.error || message || confirm.error ? (
            <Alert tone={message && !confirm.error ? "info" : "danger"}>
              {message ||
                element.error ||
                problemMessage(intent.error ?? confirm.error, t("pay.failed"))}
            </Alert>
          ) : null}
        </section>
      )}
    </main>
  );
}

/** Save a card or debit mandate from a setup link, optionally agreeing to auto-pay. Stripe
 * saves in its Payment Element; GoCardless on its own mandate page, then back here. */
export function SetupPage({ token }: { token: string }) {
  const { t } = useTranslation();
  const [autopay, setAutopay] = useState(false);
  const [chosen, setChosen] = useState("");
  const [done, setDone] = useState<null | { last4: string; auto_pay: boolean }>(null);
  const [message, setMessage] = useState("");
  const [back] = useState(returned);
  const consentKey = `tt-setup-autopay-${token}`;
  const page = useQuery({
    queryKey: ["pay-setup", token, chosen],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/pay/setup/{token}", {
          params: { path: { token }, query: chosen ? { provider: chosen } : {} },
        }),
      ),
    retry: false,
    enabled: !back,
  });
  const setup =
    page.data && !page.data.redirect_url
      ? {
          key: page.data.publishable_key,
          account: page.data.account,
          secret: page.data.client_secret,
        }
      : null;
  const element = usePaymentElement(setup);
  const complete = useMutation({
    mutationFn: async (input: {
      id: string;
      via: "" | "stripe" | "gocardless";
      consent: boolean;
    }) =>
      unwrap(
        await api.POST("/api/v1/pay/setup/{token}", {
          params: { path: { token } },
          body: { intent: input.id, autopay: input.consent, provider: input.via },
        }),
      ),
    onSuccess: (result) => setDone({ last4: result.method.last4, auto_pay: result.auto_pay }),
  });

  // Back from GoCardless's mandate page: finish with the consent given before leaving.
  useEffect(() => {
    if (back?.provider !== "gocardless") return;
    let consent = false;
    try {
      consent = window.sessionStorage.getItem(consentKey) === "1";
    } catch {
      consent = false;
    }
    complete.mutate({ id: back.intent, via: "gocardless", consent });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once, on arrival
  }, []);

  const save = async () => {
    if (!page.data) return;
    if (page.data.redirect_url) {
      try {
        window.sessionStorage.setItem(consentKey, autopay ? "1" : "0");
      } catch {
        // no storage: auto-pay can be turned on later
      }
      window.location.assign(page.data.redirect_url);
      return;
    }
    if (!element.mounted) return;
    const result = await element.mounted.stripe.confirmSetup({
      elements: element.mounted.elements,
      redirect: "if_required",
      confirmParams: { return_url: window.location.href },
    });
    if (result.error) setMessage(result.error.message ?? t("pay.failed"));
    else
      complete.mutate({
        id: result.setupIntent?.id ?? page.data.intent,
        via: "stripe",
        consent: autopay,
      });
  };

  const header = (
    <header>
      {page.data ? <BrandLine name={page.data.organisation} /> : null}
      <h1 className="text-xl font-semibold">{t("pay.setupTitle")}</h1>
      {page.data ? (
        <p className="mt-1 text-sm text-muted-foreground">{page.data.client_name}</p>
      ) : null}
    </header>
  );
  const finished = done ? (
    <Alert tone="success">
      {t("pay.setupDone", { last4: done.last4 })}
      {done.auto_pay ? ` ${t("pay.autopayOn")}` : ""}
    </Alert>
  ) : null;

  if (back?.provider === "gocardless")
    return (
      <main className={PAGE}>
        {header}
        {finished ??
          (complete.error ? (
            <Alert tone="danger">{problemMessage(complete.error, t("pay.failed"))}</Alert>
          ) : (
            <Spinner label={t("payOptions.finishing")} />
          ))}
      </main>
    );
  if (page.isPending)
    return (
      <main className={PAGE}>
        <Spinner label={t("grid.loading")} />
      </main>
    );
  if (!page.data)
    return (
      <main className={PAGE}>
        <Alert tone="danger">{t("pay.linkExpired")}</Alert>
      </main>
    );
  const redirecting = Boolean(page.data.redirect_url);
  return (
    <main className={PAGE}>
      {header}
      {finished ?? (
        <form
          className="space-y-4 rounded-xl border border-border bg-surface p-5"
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
        >
          <ProviderChoice
            providers={page.data.providers ?? []}
            value={page.data.provider}
            onChange={setChosen}
            legend={t("payOptions.saveWith")}
          />
          {redirecting ? (
            <p className="text-sm text-muted-foreground">{t("payOptions.gocardlessSetupHelp")}</p>
          ) : (
            <div ref={element.ref} />
          )}
          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              className="mt-0.5 size-4"
              checked={autopay}
              onChange={(e) => setAutopay(e.target.checked)}
            />
            <span>{page.data.consent_text}</span>
          </label>
          <Button
            type="submit"
            className="w-full"
            disabled={(!element.mounted && !redirecting) || complete.isPending}
          >
            {redirecting ? t("payOptions.continueToGoCardless") : t("pay.saveDetails")}
          </Button>
          {message || element.error || complete.error ? (
            <Alert tone="danger">
              {message || element.error || problemMessage(complete.error, t("pay.failed"))}
            </Alert>
          ) : null}
        </form>
      )}
    </main>
  );
}
