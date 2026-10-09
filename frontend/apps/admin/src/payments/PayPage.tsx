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

/** The hosted pay page for an invoice or payment request (FR-11-4). Card details are
 * entered in Stripe's own fields. */
export function PayPage({ token }: { token: string }) {
  const { t, i18n } = useTranslation();
  const [saveMethod, setSaveMethod] = useState(false);
  const [paid, setPaid] = useState(false);
  const [message, setMessage] = useState("");
  const page = useQuery({
    queryKey: ["pay", token],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/pay/{token}", { params: { path: { token } } })),
  });
  const intent = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/pay/{token}/intent", {
          params: { path: { token } },
          body: { save_method: saveMethod },
        }),
      ),
  });
  const setup = intent.data
    ? {
        key: intent.data.publishable_key,
        account: intent.data.account,
        secret: intent.data.client_secret,
      }
    : null;
  const element = usePaymentElement(setup);
  const confirm = useMutation({
    mutationFn: async (intentId: string) =>
      unwrap(
        await api.POST("/api/v1/pay/{token}/confirm", {
          params: { path: { token } },
          body: { intent: intentId },
        }),
      ),
    onSuccess: (result) => {
      if (result.status === "succeeded") setPaid(true);
      else setMessage(t("pay.processing"));
    },
  });

  // Back from a redirect (some methods leave the page to authenticate).
  useEffect(() => {
    const returned = new URLSearchParams(window.location.search).get("payment_intent");
    if (returned) confirm.mutate(returned);
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
    else confirm.mutate(result.paymentIntent?.id ?? intent.data.intent);
  };

  if (page.isPending) return <Spinner className="m-8 size-6" label={t("grid.loading")} />;
  if (!page.data)
    return (
      <main className="mx-auto max-w-lg p-6">
        <Alert tone="danger">{t("pay.notFound")}</Alert>
      </main>
    );
  const data = page.data;
  const money = (value: { amount: string; currency: string }) => formatMoney(value, i18n.language);
  const due = Number(data.amount_due.amount);

  return (
    <main className="mx-auto max-w-lg space-y-6 p-6">
      <header>
        <p className="text-sm text-muted-foreground">{data.organisation}</p>
        <h1 className="text-2xl font-semibold">
          {data.kind === "invoice"
            ? t("pay.invoiceTitle", { number: data.number })
            : t("pay.requestTitle", { number: data.number })}
        </h1>
        <p className="text-sm text-muted-foreground">
          {data.client_name}
          {data.due_date
            ? ` · ${t("pay.dueOn", { date: formatDate(data.due_date, i18n.language) })}`
            : ""}
        </p>
      </header>
      <ul className="divide-y divide-border rounded-md border border-border text-sm">
        {data.lines.map((line, i) => (
          <li key={i} className="flex justify-between gap-4 p-3">
            <span>{line.description}</span>
            <span>{money(line.amount)}</span>
          </li>
        ))}
      </ul>
      <p className="flex justify-between text-lg font-semibold">
        <span>{t("pay.amountDue")}</span>
        <span>{money(data.amount_due)}</span>
      </p>
      {data.has_pdf ? (
        <a
          className="text-sm underline-offset-2 hover:underline"
          href={`/api/v1/pay/${token}/pdf`}
          target="_blank"
          rel="noreferrer"
        >
          {t("pay.downloadPdf")}
        </a>
      ) : null}
      {paid || due === 0 ? (
        <Alert tone="success">{paid ? t("pay.thanks") : t("pay.nothingDue")}</Alert>
      ) : !data.can_pay_online ? (
        <Alert>{t("pay.offline")}</Alert>
      ) : (
        <section aria-label={t("pay.payOnline")} className="space-y-3">
          {!intent.data ? (
            <>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  className="size-4"
                  checked={saveMethod}
                  onChange={(e) => setSaveMethod(e.target.checked)}
                />
                {t("pay.saveMethod")}
              </label>
              <Button onClick={() => intent.mutate()} disabled={intent.isPending}>
                {t("pay.payAmount", { amount: money(data.amount_due) })}
              </Button>
            </>
          ) : (
            <>
              <div ref={element.ref} />
              <Button onClick={() => void pay()} disabled={!element.mounted || confirm.isPending}>
                {t("pay.payNow")}
              </Button>
            </>
          )}
          {intent.error || element.error || message || confirm.error ? (
            <Alert tone="danger">
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

/** Save a card or debit mandate from a setup link, optionally agreeing to auto-pay. */
export function SetupPage({ token }: { token: string }) {
  const { t } = useTranslation();
  const [autopay, setAutopay] = useState(false);
  const [done, setDone] = useState<null | { last4: string; auto_pay: boolean }>(null);
  const [message, setMessage] = useState("");
  const page = useQuery({
    queryKey: ["pay-setup", token],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/pay/setup/{token}", { params: { path: { token } } })),
    retry: false,
  });
  const setup = page.data
    ? {
        key: page.data.publishable_key,
        account: page.data.account,
        secret: page.data.client_secret,
      }
    : null;
  const element = usePaymentElement(setup);
  const complete = useMutation({
    mutationFn: async (intentId: string) =>
      unwrap(
        await api.POST("/api/v1/pay/setup/{token}", {
          params: { path: { token } },
          body: { intent: intentId, autopay },
        }),
      ),
    onSuccess: (result) => setDone({ last4: result.method.last4, auto_pay: result.auto_pay }),
  });

  const save = async () => {
    if (!element.mounted || !page.data) return;
    const result = await element.mounted.stripe.confirmSetup({
      elements: element.mounted.elements,
      redirect: "if_required",
      confirmParams: { return_url: window.location.href },
    });
    if (result.error) setMessage(result.error.message ?? t("pay.failed"));
    else complete.mutate(result.setupIntent?.id ?? page.data.intent);
  };

  if (page.isPending) return <Spinner className="m-8 size-6" label={t("grid.loading")} />;
  if (!page.data)
    return (
      <main className="mx-auto max-w-lg p-6">
        <Alert tone="danger">{t("pay.linkExpired")}</Alert>
      </main>
    );
  return (
    <main className="mx-auto max-w-lg space-y-6 p-6">
      <header>
        <p className="text-sm text-muted-foreground">{page.data.organisation}</p>
        <h1 className="text-2xl font-semibold">{t("pay.setupTitle")}</h1>
        <p className="text-sm text-muted-foreground">{page.data.client_name}</p>
      </header>
      {done ? (
        <Alert tone="success">
          {t("pay.setupDone", { last4: done.last4 })}
          {done.auto_pay ? ` ${t("pay.autopayOn")}` : ""}
        </Alert>
      ) : (
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
        >
          <div ref={element.ref} />
          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              className="mt-0.5 size-4"
              checked={autopay}
              onChange={(e) => setAutopay(e.target.checked)}
            />
            <span>{page.data.consent_text}</span>
          </label>
          <Button type="submit" disabled={!element.mounted || complete.isPending}>
            {t("pay.saveDetails")}
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
