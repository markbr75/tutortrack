import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, Button, Spinner, TextField } from "@tutortrack/ui";
import { useMutation } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";

import { api, fieldErrors, useMe } from "../api";
import { PublicLayout } from "../layout/PublicLayout";

/** Account → change sign-in email (FR-03-9): the link goes to the new address. */
export function EmailChangeSection() {
  const { t } = useTranslation();
  const me = useMe();
  const [form, setForm] = useState({ new_email: "", password: "" });
  const change = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/me/email", { body: form })),
    onSuccess: () => setForm({ new_email: "", password: "" }),
  });
  const errors = fieldErrors(change.error);
  return (
    <section
      className="mt-8 max-w-2xl rounded-md border border-border p-4 md:p-6"
      aria-labelledby="email-change-title"
    >
      <h2 id="email-change-title" className="text-lg font-medium">
        {t("emailChange.title")}
      </h2>
      <p className="mt-1 text-sm text-muted-foreground">
        {t("emailChange.current", { email: me.data?.user.email ?? "" })}
      </p>
      <form
        className="mt-4 flex flex-col gap-4"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          change.mutate();
        }}
      >
        {change.isSuccess ? (
          <Alert tone="success">
            {t("emailChange.sent", { email: change.data.pending_email })}
          </Alert>
        ) : null}
        {change.isError && Object.keys(errors).length === 0 ? (
          <Alert tone="danger">{change.error.message}</Alert>
        ) : null}
        <TextField
          label={t("emailChange.newEmail")}
          type="email"
          autoComplete="email"
          required
          value={form.new_email}
          error={errors.new_email}
          onChange={(e) => setForm((f) => ({ ...f, new_email: e.target.value }))}
        />
        <TextField
          label={t("emailChange.password")}
          type="password"
          autoComplete="current-password"
          hint={t("emailChange.passwordHint")}
          value={form.password}
          error={errors.password}
          onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
        />
        <div>
          <Button type="submit" loading={change.isPending}>
            {t("emailChange.submit")}
          </Button>
        </div>
      </form>
    </section>
  );
}

/** The link from the email: confirms the new address (signed in or not). */
export function ConfirmEmailPage() {
  const { t } = useTranslation();
  const token = new URLSearchParams(window.location.search).get("token") ?? "";
  const confirm = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/v1/auth/email-change/confirm", { body: { token } })),
  });
  const { mutate } = confirm;
  useEffect(() => {
    if (token) mutate();
  }, [token, mutate]);
  return (
    <PublicLayout title={t("emailChange.confirmTitle")}>
      {confirm.isSuccess ? (
        <Alert tone="success">{t("emailChange.done", { email: confirm.data.email })}</Alert>
      ) : confirm.isError || !token ? (
        <Alert tone="danger">{t("emailChange.failed")}</Alert>
      ) : (
        <p className="flex items-center gap-2" role="status">
          <Spinner /> {t("emailChange.checking")}
        </p>
      )}
    </PublicLayout>
  );
}
