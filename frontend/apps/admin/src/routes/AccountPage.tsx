import { unwrap } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";

import { api, fieldErrors, useMe } from "../api";

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mt-8 max-w-2xl rounded-md border border-border p-4 md:p-6">
      <h2 className="text-lg font-medium">{title}</h2>
      <div className="mt-4">{children}</div>
    </section>
  );
}

function ProfileSection() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { data: me } = useMe();
  const [form, setForm] = useState<Record<string, string>>({});
  useEffect(() => {
    if (me) {
      const u = me.user;
      setForm({
        first_name: u.first_name ?? "",
        last_name: u.last_name ?? "",
        preferred_name: u.preferred_name ?? "",
        pronouns: u.pronouns ?? "",
        phone: u.phone ?? "",
        timezone: u.timezone ?? "",
      });
    }
  }, [me]);
  const save = useMutation({
    mutationFn: async () => unwrap(await api.PATCH("/api/v1/me", { body: form })),
    onSuccess: (data) => queryClient.setQueryData(["me"], data),
  });
  const errors = fieldErrors(save.error);
  const field = (name: string, label: string, extra: Record<string, unknown> = {}) => (
    <TextField
      label={label}
      value={form[name] ?? ""}
      error={errors[name]}
      onChange={(e) => setForm((f) => ({ ...f, [name]: e.target.value }))}
      {...extra}
    />
  );
  return (
    <Section title={t("account.profile")}>
      <form
        className="grid gap-4 sm:grid-cols-2"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        {field("first_name", t("account.firstName"), { autoComplete: "given-name" })}
        {field("last_name", t("account.lastName"), { autoComplete: "family-name" })}
        {field("preferred_name", t("account.preferredName"))}
        {field("pronouns", t("account.pronouns"))}
        {field("phone", t("account.phone"), { type: "tel", autoComplete: "tel" })}
        {field("timezone", t("account.timezone"))}
        <div className="flex items-center gap-3 sm:col-span-2">
          <Button type="submit" loading={save.isPending}>
            {t("common.save")}
          </Button>
          {save.isSuccess ? <span role="status">{t("common.saved")}</span> : null}
        </div>
      </form>
    </Section>
  );
}

function PasswordSection() {
  const { t } = useTranslation();
  const [form, setForm] = useState({ current_password: "", new_password: "" });
  const change = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/me/password", { body: form })),
    onSuccess: () => setForm({ current_password: "", new_password: "" }),
  });
  const errors = fieldErrors(change.error);
  return (
    <Section title={t("account.password")}>
      <form
        className="flex flex-col gap-4"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          change.mutate();
        }}
      >
        {change.isSuccess ? <Alert tone="success">{t("account.passwordChanged")}</Alert> : null}
        {change.isError && Object.keys(errors).length === 0 ? (
          <Alert tone="danger">{change.error.message}</Alert>
        ) : null}
        <TextField
          label={t("account.currentPassword")}
          type="password"
          autoComplete="current-password"
          value={form.current_password}
          onChange={(e) => setForm((f) => ({ ...f, current_password: e.target.value }))}
        />
        <TextField
          label={t("account.newPassword")}
          type="password"
          autoComplete="new-password"
          hint={t("signup.passwordHint")}
          value={form.new_password}
          error={errors.new_password}
          onChange={(e) => setForm((f) => ({ ...f, new_password: e.target.value }))}
        />
        <Button type="submit" loading={change.isPending}>
          {t("account.changePassword")}
        </Button>
      </form>
    </Section>
  );
}

function RecoveryCodes({ codes }: { codes: string[] }) {
  const { t } = useTranslation();
  return (
    <Alert tone="warning" title={t("account.recoveryCodes")} className="mt-4">
      <p>{t("account.recoveryBody")}</p>
      <ul className="mt-2 grid grid-cols-2 gap-1 font-mono text-sm">
        {codes.map((c) => (
          <li key={c}>{c}</li>
        ))}
      </ul>
    </Alert>
  );
}

function MFASection() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { data: me } = useMe();
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);
  const setup = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/me/mfa/totp")),
  });
  const confirm = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/me/mfa/totp/confirm", {
          body: { device_id: setup.data?.device_id ?? "", code },
        }),
      ),
    onSuccess: (data) => {
      setCodes(data.recovery_codes);
      setup.reset();
      void queryClient.invalidateQueries({ queryKey: ["me"] });
    },
  });
  const disable = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/v1/me/mfa/disable", { body: { password } })),
    onSuccess: () => {
      setPassword("");
      setCodes(null);
      void queryClient.invalidateQueries({ queryKey: ["me"] });
    },
  });
  const regenerate = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/v1/me/mfa/recovery-codes", { body: { password } })),
    onSuccess: (data) => setCodes(data.recovery_codes),
  });

  if (me?.user.has_mfa) {
    return (
      <Section title={t("account.mfa")}>
        <p className="text-sm">{t("account.mfaOn")}</p>
        {codes ? <RecoveryCodes codes={codes} /> : null}
        <div className="mt-4 flex flex-wrap items-end gap-3">
          <TextField
            label={t("account.confirmPassword")}
            type="password"
            autoComplete="current-password"
            value={password}
            error={disable.isError ? disable.error.message : undefined}
            onChange={(e) => setPassword(e.target.value)}
          />
          <Button variant="secondary" disabled={!password} onClick={() => regenerate.mutate()}>
            {t("account.newRecoveryCodes")}
          </Button>
          <Button variant="danger" disabled={!password} onClick={() => disable.mutate()}>
            {t("account.mfaDisable")}
          </Button>
        </div>
      </Section>
    );
  }
  return (
    <Section title={t("account.mfa")}>
      {codes ? <RecoveryCodes codes={codes} /> : <p className="text-sm">{t("account.mfaOff")}</p>}
      {setup.data ? (
        <form
          className="mt-4 flex flex-col gap-4"
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            confirm.mutate();
          }}
        >
          <p className="text-sm">{t("account.mfaScan")}</p>
          <div
            className="w-fit rounded-md bg-white p-2"
            role="img"
            aria-label={setup.data.otpauth_uri}
            // Server-generated SVG (segno) for the otpauth URI; no user input is embedded.
            dangerouslySetInnerHTML={{ __html: setup.data.qr_svg }}
          />
          <code className="text-sm break-all">{setup.data.secret}</code>
          <TextField
            label={t("account.mfaConfirm")}
            inputMode="numeric"
            autoComplete="one-time-code"
            value={code}
            error={confirm.isError ? confirm.error.message : undefined}
            onChange={(e) => setCode(e.target.value)}
          />
          <Button type="submit" loading={confirm.isPending}>
            {t("account.mfaEnable")}
          </Button>
        </form>
      ) : (
        <Button className="mt-4" loading={setup.isPending} onClick={() => setup.mutate()}>
          {t("account.mfaSetup")}
        </Button>
      )}
    </Section>
  );
}

function SessionsSection() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const sessions = useQuery({
    queryKey: ["sessions"],
    queryFn: async () => unwrap(await api.GET("/api/v1/me/sessions")),
  });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["sessions"] });
  const revoke = useMutation({
    mutationFn: async (id: string) =>
      unwrap(await api.DELETE("/api/v1/me/sessions/{id}", { params: { path: { id } } })),
    onSuccess: refresh,
  });
  const revokeAll = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/me/sessions/revoke-all")),
    onSuccess: refresh,
  });
  return (
    <Section title={t("account.sessions")}>
      <ul className="divide-y divide-border">
        {sessions.data?.map((s) => (
          <li key={s.id} className="flex items-center justify-between gap-4 py-2 text-sm">
            <span>
              <span className="block">{s.user_agent || s.ip}</span>
              <span className="text-muted-foreground">
                {s.is_current
                  ? t("account.thisDevice")
                  : t("account.lastSeen", {
                      when: s.last_seen_at ? formatDateTime(s.last_seen_at, i18n.language) : "",
                    })}
              </span>
            </span>
            {!s.is_current ? (
              <Button size="sm" variant="ghost" onClick={() => revoke.mutate(s.id)}>
                {t("account.signOutSession")}
              </Button>
            ) : null}
          </li>
        ))}
      </ul>
      <Button className="mt-4" variant="secondary" onClick={() => revokeAll.mutate()}>
        {t("account.signOutOthers")}
      </Button>
    </Section>
  );
}

export function AccountPage() {
  const { t } = useTranslation();
  return (
    <div>
      <h1 className="text-2xl font-semibold">{t("account.title")}</h1>
      <ProfileSection />
      <PasswordSection />
      <MFASection />
      <SessionsSection />
    </div>
  );
}
