import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, Button, TextField } from "@tutortrack/ui";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { api, fieldErrors, useMe } from "../api";
import { PublicLayout } from "../layout/PublicLayout";

export function AcceptInvitePage() {
  const { t } = useTranslation();
  const token = new URLSearchParams(window.location.search).get("token") ?? "";
  const me = useMe();
  const lookup = useQuery({
    queryKey: ["invitation", token],
    enabled: !!token,
    retry: false,
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/invitations/lookup", { params: { query: { token } } })),
  });
  const [form, setForm] = useState({ first_name: "", last_name: "", password: "" });
  const accept = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/v1/invitations/accept", { body: { token, ...form } })),
    onSuccess: () => window.location.assign("/"),
  });
  const errors = fieldErrors(accept.error);
  const invitation = lookup.data;

  if (!token || lookup.isError) {
    return (
      <PublicLayout title={t("app.name")}>
        <Alert tone="danger">{t("invite.invalid")}</Alert>
      </PublicLayout>
    );
  }
  if (!invitation) {
    return <PublicLayout title={t("app.name")}>{t("common.loading")}</PublicLayout>;
  }
  const signedInAsInvitee = me.data?.user.email === invitation.email;
  const next = encodeURIComponent(`/accept-invite?token=${token}`);
  return (
    <PublicLayout
      title={t("invite.title", { organisation: invitation.organisation_name })}
      subtitle={t("invite.body", { role: t(`roles.${invitation.role}`), email: invitation.email })}
    >
      {accept.isError && Object.keys(errors).length === 0 ? (
        <Alert tone="danger">{accept.error.message}</Alert>
      ) : null}
      {signedInAsInvitee ? (
        <Button loading={accept.isPending} onClick={() => accept.mutate()}>
          {t("invite.accept")}
        </Button>
      ) : invitation.account_exists ? (
        <Alert tone="info">
          {t("invite.signInFirst", { email: invitation.email })}{" "}
          <a className="underline" href={`/login?next=${next}`}>
            {t("auth.signInAction")}
          </a>
        </Alert>
      ) : (
        <form
          className="flex flex-col gap-4"
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            accept.mutate();
          }}
        >
          <p className="text-sm font-medium">{t("invite.create")}</p>
          <TextField
            label={t("signup.firstName")}
            autoComplete="given-name"
            value={form.first_name}
            error={errors.first_name}
            onChange={(e) => setForm((f) => ({ ...f, first_name: e.target.value }))}
          />
          <TextField
            label={t("signup.lastName")}
            autoComplete="family-name"
            value={form.last_name}
            onChange={(e) => setForm((f) => ({ ...f, last_name: e.target.value }))}
          />
          <TextField
            label={t("signup.password")}
            type="password"
            autoComplete="new-password"
            hint={t("signup.passwordHint")}
            value={form.password}
            error={errors.password}
            onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
          />
          <Button type="submit" loading={accept.isPending}>
            {t("invite.accept")}
          </Button>
        </form>
      )}
    </PublicLayout>
  );
}
