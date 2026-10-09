import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, TextField } from "@tutortrack/ui";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";

import { api, fieldErrors } from "../api";
import { PublicLayout } from "../layout/PublicLayout";

const COUNTRIES = ["GB", "IE", "US", "CA", "AU", "NZ", "FR", "DE", "ES", "NL"] as const;
const BUSINESS_TYPES = ["sole_trader", "team", "agency", "centre", "online"] as const;

declare global {
  interface Window {
    onTurnstileToken?: (token: string) => void;
  }
}

/** Cloudflare Turnstile widget, only when the backend has a site key configured. */
function Turnstile({ siteKey, onToken }: { siteKey: string; onToken: (token: string) => void }) {
  useEffect(() => {
    window.onTurnstileToken = onToken;
    const script = document.createElement("script");
    script.src = "https://challenges.cloudflare.com/turnstile/v0/api.js";
    script.async = true;
    document.head.appendChild(script);
    return () => {
      script.remove();
      delete window.onTurnstileToken;
    };
  }, [onToken]);
  return <div className="cf-turnstile" data-sitekey={siteKey} data-callback="onTurnstileToken" />;
}

export function SignupPage() {
  const { t } = useTranslation();
  const [form, setForm] = useState({
    first_name: "",
    last_name: "",
    email: "",
    password: "",
    business_name: "",
    country: "GB",
    business_type: "sole_trader",
  });
  const [token, setToken] = useState("");
  const config = useQuery({
    queryKey: ["signup-config"],
    queryFn: async () => unwrap(await api.GET("/api/v1/signup/config")),
  });
  const siteKey = config.data?.turnstile_site_key ?? "";

  const signup = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/signup", {
          body: {
            ...form,
            business_type: form.business_type as (typeof BUSINESS_TYPES)[number],
            timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
            turnstile_token: token,
          },
        }),
      ),
    onSuccess: (data) => window.location.assign(data.continue_url),
  });
  const errors = fieldErrors(signup.error);
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [key]: e.target.value }));

  function submit(event: FormEvent) {
    event.preventDefault();
    signup.mutate();
  }

  return (
    <PublicLayout title={t("signup.title")} subtitle={t("signup.subtitle")}>
      <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
        {signup.isError && Object.keys(errors).length === 0 ? (
          <Alert tone="danger">{signup.error.message}</Alert>
        ) : null}
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField
            label={t("signup.firstName")}
            autoComplete="given-name"
            required
            value={form.first_name}
            onChange={set("first_name")}
            error={errors.first_name}
          />
          <TextField
            label={t("signup.lastName")}
            autoComplete="family-name"
            value={form.last_name}
            onChange={set("last_name")}
            error={errors.last_name}
          />
        </div>
        <TextField
          label={t("signup.email")}
          type="email"
          autoComplete="email"
          required
          value={form.email}
          onChange={set("email")}
          error={errors.email}
        />
        <TextField
          label={t("signup.password")}
          type="password"
          autoComplete="new-password"
          required
          hint={t("signup.passwordHint")}
          value={form.password}
          onChange={set("password")}
          error={errors.password}
        />
        <TextField
          label={t("signup.businessName")}
          autoComplete="organization"
          required
          value={form.business_name}
          onChange={set("business_name")}
          error={errors.business_name ?? errors.slug}
        />
        <div className="grid gap-4 sm:grid-cols-2">
          <SelectField
            label={t("signup.country")}
            value={form.country}
            onChange={set("country")}
            options={COUNTRIES.map((c) => ({ value: c, label: t(`countries.${c}`) }))}
            error={errors.country}
          />
          <SelectField
            label={t("signup.businessType")}
            value={form.business_type}
            onChange={set("business_type")}
            options={BUSINESS_TYPES.map((b) => ({ value: b, label: t(`businessTypes.${b}`) }))}
          />
        </div>
        {siteKey ? <Turnstile siteKey={siteKey} onToken={setToken} /> : null}
        <Button type="submit" loading={signup.isPending} disabled={!!siteKey && !token}>
          {t("signup.submit")}
        </Button>
      </form>
    </PublicLayout>
  );
}
