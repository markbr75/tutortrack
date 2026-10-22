import { unwrap } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  FormPanel,
  NamePlate,
  PageHeader,
  PanelRow,
  PanelRows,
  RuledPanel,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";

import { api, fieldErrors, useMe } from "../api";
import { DigestPreferences } from "../comms/DigestPreferences";
import { SavedNote } from "../components/SavedNote";
import { AccountDeletionSection } from "./AccountDeletionSection";
import { EmailChangeSection } from "./EmailChange";
import { describeAgent } from "./device";
import { createPasskey, passkeysSupported } from "./webauthn";

const quiet = "text-muted-foreground";
const SESSIONS_SHOWN = 5;

/** "Chrome on Windows", or the raw agent (or IP) when it can't be read. */
function useDeviceName() {
  const { t } = useTranslation();
  return (agent: string, fallback: string) => {
    const d = describeAgent(agent);
    if (!d) return agent || fallback;
    if (d.browser && d.os) return t("designS9b.account.device", d);
    return d.browser || d.os;
  };
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
    <FormPanel
      title={t("account.profile")}
      submit={t("common.save")}
      pending={save.isPending}
      onSubmit={() => save.mutate()}
      error={
        save.isError && !Object.keys(errors).length ? (
          <Alert tone="danger">{save.error.message}</Alert>
        ) : null
      }
      trail={<SavedNote show={save.isSuccess} />}
    >
      {field("first_name", t("account.firstName"), { autoComplete: "given-name" })}
      {field("last_name", t("account.lastName"), { autoComplete: "family-name" })}
      {field("preferred_name", t("account.preferredName"))}
      {field("pronouns", t("account.pronouns"))}
      {field("phone", t("account.phone"), { type: "tel", autoComplete: "tel" })}
      {field("timezone", t("account.timezone"))}
    </FormPanel>
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
    <FormPanel
      title={t("account.password")}
      submit={t("account.changePassword")}
      pending={change.isPending}
      onSubmit={() => change.mutate()}
      error={
        change.isSuccess ? (
          <Alert tone="success">{t("account.passwordChanged")}</Alert>
        ) : change.isError && Object.keys(errors).length === 0 ? (
          <Alert tone="danger">{change.error.message}</Alert>
        ) : null
      }
    >
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
    </FormPanel>
  );
}

function RecoveryCodes({ codes }: { codes: string[] }) {
  const { t } = useTranslation();
  return (
    <Alert tone="warning" title={t("account.recoveryCodes")}>
      <p>{t("account.recoveryBody")}</p>
      <ul className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 font-medium tracking-wide tabular-nums sm:w-fit">
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
      <RuledPanel
        title={t("account.mfa")}
        description={t("account.mfaOn")}
        bodyClassName="space-y-3"
        footer={
          <>
            <Button
              variant="secondary"
              disabled={!password}
              loading={regenerate.isPending}
              onClick={() => regenerate.mutate()}
            >
              {t("account.newRecoveryCodes")}
            </Button>
            <Button
              variant="danger"
              disabled={!password}
              loading={disable.isPending}
              onClick={() => disable.mutate()}
            >
              {t("account.mfaDisable")}
            </Button>
          </>
        }
      >
        {codes ? <RecoveryCodes codes={codes} /> : null}
        <div className="sm:max-w-sm">
          <TextField
            label={t("account.confirmPassword")}
            type="password"
            autoComplete="current-password"
            value={password}
            error={disable.isError ? disable.error.message : undefined}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
      </RuledPanel>
    );
  }
  if (setup.data) {
    return (
      <form
        aria-labelledby="mfa-title"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          confirm.mutate();
        }}
      >
        <RuledPanel
          titleId="mfa-title"
          title={t("account.mfa")}
          description={t("account.mfaScan")}
          bodyClassName="space-y-4"
          footer={
            <Button type="submit" loading={confirm.isPending}>
              {t("account.mfaEnable")}
            </Button>
          }
        >
          <div className="flex flex-wrap items-center gap-4">
            {/* A QR code must stay dark on light to scan, in either colour scheme. */}
            <div
              className="w-fit rounded-md border border-border bg-[#fff] p-2"
              role="img"
              aria-label={setup.data.otpauth_uri}
              // Server-generated SVG (segno) for the otpauth URI; no user input is embedded.
              dangerouslySetInnerHTML={{ __html: setup.data.qr_svg }}
            />
            <p className="min-w-0 text-sm font-medium tracking-wide break-all select-all tabular-nums">
              {setup.data.secret}
            </p>
          </div>
          <div className="sm:max-w-sm">
            <TextField
              label={t("account.mfaConfirm")}
              inputMode="numeric"
              autoComplete="one-time-code"
              className="tabular-nums"
              value={code}
              error={confirm.isError ? confirm.error.message : undefined}
              onChange={(e) => setCode(e.target.value)}
            />
          </div>
        </RuledPanel>
      </form>
    );
  }
  return (
    <RuledPanel
      title={t("account.mfa")}
      description={codes ? undefined : t("account.mfaOff")}
      flush={!codes}
      footer={
        <Button variant="secondary" loading={setup.isPending} onClick={() => setup.mutate()}>
          {t("account.mfaSetup")}
        </Button>
      }
    >
      {codes ? <RecoveryCodes codes={codes} /> : null}
    </RuledPanel>
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
  const [all, setAll] = useState(false);
  const deviceName = useDeviceName();
  // This device first, then the most recently active; long lists show the first few.
  const sorted = [...(sessions.data ?? [])].sort(
    (a, b) =>
      Number(b.is_current) - Number(a.is_current) ||
      (b.last_seen_at ?? "").localeCompare(a.last_seen_at ?? ""),
  );
  const visible = all ? sorted : sorted.slice(0, SESSIONS_SHOWN);
  return (
    <RuledPanel
      flush
      title={t("account.sessions")}
      aside={
        sessions.data ? (
          <span className="text-muted-foreground tabular-nums">
            {t("designS9b.account.sessionCount", { count: sorted.length })}
          </span>
        ) : null
      }
      footer={
        <>
          <Button
            variant="secondary"
            size="sm"
            loading={revokeAll.isPending}
            onClick={() => revokeAll.mutate()}
          >
            {t("account.signOutOthers")}
          </Button>
          {sorted.length > SESSIONS_SHOWN ? (
            <Button
              variant="ghost"
              size="sm"
              aria-expanded={all}
              className="text-link"
              onClick={() => setAll((v) => !v)}
            >
              {all
                ? t("designS9b.account.showFewer")
                : t("designS9b.account.showAll", { count: sorted.length })}
            </Button>
          ) : null}
        </>
      }
    >
      <PanelRows>
        {visible.map((s) => (
          <PanelRow key={s.id}>
            <NamePlate
              name={<span title={s.user_agent}>{deviceName(s.user_agent ?? "", s.ip ?? "")}</span>}
              context={
                <span className="tabular-nums">
                  {[
                    s.is_current
                      ? t("account.thisDevice")
                      : t("account.lastSeen", {
                          when: s.last_seen_at ? formatDateTime(s.last_seen_at, i18n.language) : "",
                        }),
                    s.ip,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              }
              aside={
                !s.is_current ? (
                  <Button
                    size="sm"
                    variant="ghost"
                    className={`${quiet} max-sm:-ml-3`}
                    onClick={() => revoke.mutate(s.id)}
                  >
                    {t("account.signOutSession")}
                  </Button>
                ) : null
              }
            />
          </PanelRow>
        ))}
      </PanelRows>
    </RuledPanel>
  );
}

function LoginHistorySection() {
  const { t, i18n } = useTranslation();
  const logins = useQuery({
    queryKey: ["me-logins"],
    queryFn: async () => unwrap(await api.GET("/api/v1/me/logins")),
  });
  const rows = logins.data?.slice(0, 10) ?? [];
  const deviceName = useDeviceName();
  return (
    <RuledPanel flush title={t("account.logins")}>
      {logins.data && !rows.length ? (
        <p className="px-5 py-4 text-sm text-muted-foreground">{t("designS9b.account.noLogins")}</p>
      ) : (
        <PanelRows>
          {rows.map((e) => (
            <PanelRow key={e.id}>
              <p>
                <span className={e.success ? "font-medium" : "font-medium text-danger"}>
                  {e.success ? t("account.loginOk") : t("account.loginFailed")}
                </span>
                {" · "}
                <time dateTime={e.created_at} className="tabular-nums">
                  {formatDateTime(e.created_at, i18n.language)}
                </time>
              </p>
              <p className="text-xs break-words text-muted-foreground tabular-nums">
                {[`${e.ip}${e.country ? ` (${e.country})` : ""}`, deviceName(e.user_agent, "")]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
            </PanelRow>
          ))}
        </PanelRows>
      )}
    </RuledPanel>
  );
}

/** Passkeys and security keys (E03-T08). The first one turns on two-step sign-in. */
function PasskeysSection() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [codes, setCodes] = useState<string[]>([]);
  const keys = useQuery({
    queryKey: ["me", "passkeys"],
    queryFn: async () => unwrap(await api.GET("/api/v1/me/passkeys")),
  });
  const add = useMutation({
    mutationFn: async () => {
      const options = unwrap(await api.POST("/api/v1/me/passkeys/options"));
      const credential = await createPasskey(options as Record<string, unknown>);
      return unwrap(await api.POST("/api/v1/me/passkeys/register", { body: { credential, name } }));
    },
    onSuccess: (data) => {
      setName("");
      setCodes(data.recovery_codes);
      void queryClient.invalidateQueries({ queryKey: ["me"] });
    },
  });
  const remove = useMutation({
    mutationFn: async (id: string) =>
      unwrap(await api.DELETE("/api/v1/me/passkeys/{id}", { params: { path: { id } } })),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["me"] }),
  });
  const list = keys.data ?? [];
  return (
    <RuledPanel flush title={t("passkeys.title")} description={t("passkeys.intro")}>
      {list.length ? (
        <PanelRows>
          {list.map((key) => (
            <PanelRow key={key.id}>
              <NamePlate
                name={key.name}
                context={
                  <span className="tabular-nums">
                    {key.last_used_at
                      ? t("passkeys.lastUsed", {
                          when: formatDateTime(key.last_used_at, i18n.language),
                        })
                      : t("passkeys.neverUsed")}
                  </span>
                }
                aside={
                  <Button
                    size="sm"
                    variant="ghost"
                    className={`${quiet} max-sm:-ml-3`}
                    aria-label={t("passkeys.removeNamed", { name: key.name })}
                    onClick={() => remove.mutate(key.id)}
                  >
                    {t("passkeys.remove")}
                  </Button>
                }
              />
            </PanelRow>
          ))}
        </PanelRows>
      ) : null}
      <div
        className={list.length ? "space-y-3 border-t border-rule px-5 py-4" : "space-y-3 px-5 py-4"}
      >
        {passkeysSupported() ? (
          <form
            className="flex flex-wrap items-end gap-3"
            onSubmit={(e: FormEvent) => {
              e.preventDefault();
              add.mutate();
            }}
          >
            <div className="min-w-56 flex-1 sm:max-w-sm">
              <TextField
                label={t("passkeys.name")}
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </div>
            <Button type="submit" variant="secondary" loading={add.isPending}>
              {t("passkeys.add")}
            </Button>
          </form>
        ) : (
          <p className="text-sm text-muted-foreground">{t("passkeys.unsupported")}</p>
        )}
        {add.isError ? <Alert tone="danger">{t("passkeys.failed")}</Alert> : null}
        {codes.length ? <RecoveryCodes codes={codes} /> : null}
      </div>
    </RuledPanel>
  );
}

export function AccountPage() {
  const { t } = useTranslation();
  return (
    <div className="max-w-3xl">
      <PageHeader title={t("account.title")} description={t("designS9b.account.description")} />
      <div className="space-y-6">
        <ProfileSection />
        <EmailChangeSection />
        <PasswordSection />
        <MFASection />
        <PasskeysSection />
        <SessionsSection />
        <LoginHistorySection />
        <DigestPreferences />
        <AccountDeletionSection />
      </div>
    </div>
  );
}
