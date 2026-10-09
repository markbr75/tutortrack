import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useEffect, useState, type FormEvent } from "react";

import { api, fieldErrors, type OnboardingState } from "../api";
import { PublicLayout } from "../layout/PublicLayout";

type Values = Record<string, string>;

interface FieldDef {
  name: string;
  label: string;
  type?: "text" | "email" | "number" | "color" | "textarea" | "select";
  options?: { value: string; label: string }[];
  optional?: boolean;
}

const BUSINESS_TYPES = ["sole_trader", "team", "agency", "centre", "online"];
const TEAM_SIZES = ["1", "2-5", "6-20", "21-100", "100+"];
const CURRENCIES = ["GBP", "EUR", "USD", "AUD", "CAD", "NZD"];

function useSteps(t: (key: string) => string): Record<string, FieldDef[]> {
  return {
    business: [
      {
        name: "business_type",
        label: t("signup.businessType"),
        type: "select",
        options: BUSINESS_TYPES.map((b) => ({ value: b, label: t(`businessTypes.${b}`) })),
      },
      {
        name: "team_size",
        label: t("onboarding.teamSize"),
        type: "select",
        options: TEAM_SIZES.map((s) => ({ value: s, label: s })),
      },
    ],
    locale: [
      {
        name: "locale",
        label: t("onboarding.locale"),
        type: "select",
        options: [
          { value: "en-GB", label: "English (UK)" },
          { value: "en-US", label: "English (US)" },
        ],
      },
      {
        name: "default_currency",
        label: t("onboarding.currency"),
        type: "select",
        options: CURRENCIES.map((c) => ({ value: c, label: c })),
      },
      { name: "timezone", label: t("onboarding.timezone") },
    ],
    branding: [{ name: "primary_colour", label: t("onboarding.colour"), type: "color" }],
    service: [
      { name: "subject", label: t("onboarding.subject") },
      { name: "level", label: t("onboarding.level"), optional: true },
      { name: "duration_minutes", label: t("onboarding.duration"), type: "number" },
      { name: "price", label: t("onboarding.price"), type: "number" },
    ],
    tutors: [{ name: "emails", label: t("onboarding.tutorEmails"), type: "textarea" }],
    students: [
      { name: "student_first_name", label: t("onboarding.studentFirstName") },
      { name: "student_last_name", label: t("onboarding.studentLastName"), optional: true },
      { name: "contact_name", label: t("onboarding.contactName"), optional: true },
      { name: "contact_email", label: t("onboarding.contactEmail"), type: "email", optional: true },
    ],
    payments: [
      {
        name: "provider",
        label: t("onboarding.steps.payments"),
        type: "select",
        options: [
          { value: "later", label: t("onboarding.paymentsLater") },
          { value: "stripe", label: t("onboarding.paymentsStripe") },
        ],
      },
    ],
    invoicing: [
      {
        name: "invoicing_style",
        label: t("onboarding.steps.invoicing"),
        type: "select",
        options: ["payg", "monthly_advance", "packages"].map((s) => ({
          value: s,
          label: t(`onboarding.invoicing.${s}`),
        })),
      },
    ],
  };
}

const DEFAULTS: Record<string, Values> = {
  business: { business_type: "sole_trader", team_size: "1" },
  locale: {
    locale: "en-GB",
    default_currency: "GBP",
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
  },
  branding: { primary_colour: "#2563eb" },
  service: { duration_minutes: "60" },
  payments: { provider: "later" },
  invoicing: { invoicing_style: "payg" },
};

/** Turns form strings into the step's API payload. */
function toPayload(step: string, values: Values, currency: string): Record<string, unknown> {
  if (step === "service") {
    return {
      subject: values.subject ?? "",
      level: values.level ?? "",
      duration_minutes: Number(values.duration_minutes),
      price: { amount: values.price ?? "", currency },
    };
  }
  if (step === "tutors") {
    return { emails: (values.emails ?? "").split(/\s+/).filter(Boolean) };
  }
  return values;
}

function useHandoff(): "pending" | "done" | "failed" {
  const [status, setStatus] = useState<"pending" | "done" | "failed">(() =>
    new URLSearchParams(window.location.search).has("handoff") ? "pending" : "done",
  );
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const token = params.get("handoff");
    if (!token) return;
    params.delete("handoff");
    const query = params.toString();
    window.history.replaceState(null, "", window.location.pathname + (query ? `?${query}` : ""));
    void api
      .POST("/api/v1/auth/handoff", { body: { token } })
      .then((result) => setStatus(result.response.ok ? "done" : "failed"));
  }, []);
  return status;
}

export function OnboardingPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const handoff = useHandoff();
  const steps = useSteps(t);
  const [step, setStep] = useState<string | null>(null);
  const [values, setValues] = useState<Values>({});
  const [currency, setCurrency] = useState("GBP");

  const state = useQuery({
    queryKey: ["onboarding"],
    enabled: handoff === "done",
    queryFn: async () => unwrap(await api.GET("/api/v1/onboarding/state")),
  });
  const keys = state.data?.steps.map((s) => s.key) ?? [];
  const current = step ?? (state.data?.current_step || keys[0]) ?? null;

  useEffect(() => {
    if (!current) return;
    const saved = (state.data?.answers[current] ?? {}) as Record<string, unknown>;
    const asStrings = Object.fromEntries(
      Object.entries(saved).map(([k, v]) => [
        k,
        k === "price" ? String((v as { amount: string }).amount) : Array.isArray(v) ? v.join("\n") : String(v),
      ]),
    );
    setValues({ ...(DEFAULTS[current] ?? {}), ...asStrings });
  }, [current, state.data]);

  const submit = useMutation({
    mutationFn: async ({ key, skip }: { key: string; skip: boolean }) =>
      unwrap(
        await api.POST("/api/v1/onboarding/{step}", {
          params: { path: { step: key } },
          body: (skip ? { skip: true } : toPayload(key, values, currency)) as never,
        }),
      ),
    onSuccess: (data: OnboardingState, { key }) => {
      if (key === "locale") setCurrency(values.default_currency ?? currency);
      queryClient.setQueryData(["onboarding"], data);
      if (key === "complete") {
        void queryClient.invalidateQueries();
        void navigate({ to: "/" });
        return;
      }
      if (!data.current_step) {
        submit.mutate({ key: "complete", skip: false });
        return;
      }
      setStep(data.current_step);
    },
  });
  const demo = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/demo-data")),
  });
  const errors = fieldErrors(submit.error);

  if (handoff === "failed" || state.isError) {
    return (
      <PublicLayout title={t("onboarding.title")}>
        <Alert tone="danger">{t("onboarding.handoffFailed")}</Alert>
      </PublicLayout>
    );
  }
  if (!state.data || !current) {
    return (
      <div className="grid h-screen place-items-center">
        <Spinner className="size-6" label={t("common.loading")} />
      </div>
    );
  }

  const index = keys.indexOf(current);
  const fields = steps[current] ?? [];
  const isLast = index === keys.length - 1;

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    submit.mutate({ key: current as string, skip: false });
  }

  return (
    <PublicLayout title={t("onboarding.title")} wide>
      <p className="text-sm text-muted-foreground">
        {t("onboarding.progress", { current: index + 1, total: keys.length })}
      </p>
      <ol className="mt-2 flex gap-1" aria-hidden="true">
        {state.data.steps.map((s) => (
          <li
            key={s.key}
            className={`h-1.5 flex-1 rounded ${s.status === "pending" ? "bg-muted" : "bg-brand"}`}
          />
        ))}
      </ol>
      <form onSubmit={onSubmit} className="mt-6 flex flex-col gap-4" noValidate>
        <h2 className="text-lg font-medium">{t(`onboarding.steps.${current}`)}</h2>
        {current === "payments" ? <p className="text-sm">{t("onboarding.paymentsBody")}</p> : null}
        {submit.isError && Object.keys(errors).length === 0 ? (
          <Alert tone="danger">{submit.error.message}</Alert>
        ) : null}
        {fields.map((field) => {
          const common = {
            label: field.optional ? `${field.label} (${t("common.optional")})` : field.label,
            value: values[field.name] ?? "",
            error: errors[field.name],
          };
          const onChange = (e: { target: { value: string } }) =>
            setValues((v) => ({ ...v, [field.name]: e.target.value }));
          if (field.type === "select") {
            return (
              <SelectField
                key={field.name}
                {...common}
                options={field.options ?? []}
                onChange={onChange}
              />
            );
          }
          if (field.type === "textarea") {
            return (
              <div key={field.name} className="flex flex-col gap-1">
                <label htmlFor={`f-${field.name}`} className="text-sm font-medium">
                  {common.label}
                </label>
                <textarea
                  id={`f-${field.name}`}
                  rows={4}
                  className="rounded-md border border-border bg-background p-3 text-sm"
                  value={common.value}
                  aria-describedby={`f-${field.name}-hint`}
                  onChange={onChange}
                />
                <p id={`f-${field.name}-hint`} className="text-xs text-muted-foreground">
                  {t("onboarding.tutorEmailsHint")}
                </p>
                {common.error ? (
                  <p className="text-xs text-danger" role="alert">
                    {common.error}
                  </p>
                ) : null}
              </div>
            );
          }
          return (
            <TextField
              key={field.name}
              {...common}
              type={field.type ?? "text"}
              inputMode={field.type === "number" ? "decimal" : undefined}
              onChange={onChange}
            />
          );
        })}
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {index > 0 ? (
            <Button type="button" variant="ghost" onClick={() => setStep(keys[index - 1] ?? null)}>
              {t("common.back")}
            </Button>
          ) : null}
          <Button
            type="button"
            variant="secondary"
            onClick={() => submit.mutate({ key: current, skip: true })}
          >
            {t("common.skip")}
          </Button>
          <Button type="submit" loading={submit.isPending}>
            {isLast ? t("onboarding.finish") : t("common.next")}
          </Button>
          <Button
            type="button"
            variant="ghost"
            className="ml-auto"
            onClick={() => submit.mutate({ key: "complete", skip: false })}
          >
            {t("onboarding.finish")}
          </Button>
        </div>
      </form>
      <div className="mt-10 border-t border-border pt-6">
        {demo.isSuccess ? (
          <Alert tone="success">{t("onboarding.demoLoaded")}</Alert>
        ) : (
          <Button variant="secondary" loading={demo.isPending} onClick={() => demo.mutate()}>
            {t("onboarding.demo")}
          </Button>
        )}
      </div>
    </PublicLayout>
  );
}
