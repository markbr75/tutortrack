import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  buttonClass,
  CheckboxField,
  cn,
  RuledPanel,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { api, safeNext } from "../api";
import { PublicLayout, usePublicBranding } from "../layout/PublicLayout";
import { getPasskey, passkeysSupported } from "./webauthn";

/** Sign in with a passkey (E03-T08): passkey-only, or as the second factor while a
 * password or magic-link sign-in waits for it. */
function usePasskeySignIn(onDone: () => void) {
  return useMutation({
    mutationFn: async () => {
      const options = unwrap(await api.POST("/api/v1/auth/passkey/options"));
      const credential = await getPasskey(options as Record<string, unknown>);
      return unwrap(
        await api.POST("/api/v1/auth/passkey/verify", { body: { credential, remember: false } }),
      );
    },
    onSuccess: onDone,
  });
}

/** A text link in link ink, underlined on hover. */
const LINK = "font-medium text-link underline-offset-2 hover:underline";

function params() {
  return new URLSearchParams(window.location.search);
}

/** Second sign-in step: TOTP or a recovery code. */
export function MFAStep({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation();
  const [code, setCode] = useState("");
  const verify = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/auth/mfa/verify", { body: { code } })),
    onSuccess: onDone,
  });
  const passkey = usePasskeySignIn(onDone);
  return (
    <form
      className="flex flex-col gap-4 rounded-xl border border-border bg-surface p-5"
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        verify.mutate();
      }}
    >
      <div>
        <h2 className="text-base font-semibold">{t("auth.mfaTitle")}</h2>
        <p className="mt-0.5 text-sm text-muted-foreground">{t("auth.mfaBody")}</p>
      </div>
      <TextField
        label={t("auth.mfaCode")}
        autoComplete="one-time-code"
        inputMode="numeric"
        autoFocus
        value={code}
        onChange={(e) => setCode(e.target.value)}
        error={verify.isError ? verify.error.message : undefined}
      />
      <Button type="submit" loading={verify.isPending}>
        {t("auth.mfaSubmit")}
      </Button>
      {passkeysSupported() ? (
        <Button variant="secondary" loading={passkey.isPending} onClick={() => passkey.mutate()}>
          {t("passkeys.useInstead")}
        </Button>
      ) : null}
      {passkey.isError ? <Alert tone="danger">{t("passkeys.failed")}</Alert> : null}
    </form>
  );
}

export function LoginPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const next = safeNext(params().get("next"));
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(false);
  const [mfa, setMfa] = useState(params().get("mfa") === "1");
  const ssoError = params().get("error");

  const providers = useQuery({
    queryKey: ["sso-providers"],
    queryFn: async () => unwrap(await api.GET("/api/v1/auth/sso/providers")),
  });
  const finish = () => {
    void queryClient.invalidateQueries();
    window.location.assign(next);
  };
  const login = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/v1/auth/login", { body: { email, password, remember } })),
    onSuccess: (data) => (data.mfa_required ? setMfa(true) : finish()),
  });
  const magic = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/v1/auth/magic-link", { body: { email, next } })),
  });
  const passkey = usePasskeySignIn(finish);
  const brand = usePublicBranding();
  const orgSso = useQuery({
    queryKey: ["org-sso"],
    queryFn: async () => unwrap(await api.GET("/api/v1/auth/org-sso")),
  });

  if (mfa) {
    return (
      <PublicLayout title={t("auth.signInTitle")}>
        <MFAStep onDone={finish} />
      </PublicLayout>
    );
  }

  const secondary = cn(buttonClass({ variant: "secondary" }), "w-full");
  return (
    <PublicLayout title={t("auth.signInTitle")}>
      <div className="flex flex-col gap-4">
        {ssoError ? <Alert tone="danger">{t("auth.ssoError")}</Alert> : null}
        {magic.isSuccess ? <Alert tone="success">{t("auth.magicLinkSent")}</Alert> : null}
        <RuledPanel>
          <form
            className="flex flex-col gap-4"
            onSubmit={(e: FormEvent) => {
              e.preventDefault();
              login.mutate();
            }}
          >
            {login.isError ? <Alert tone="danger">{login.error.message}</Alert> : null}
            <TextField
              label={t("auth.email")}
              type="email"
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <TextField
              label={t("auth.password")}
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            <CheckboxField
              label={t("auth.remember")}
              checked={remember}
              onChange={(e) => setRemember(e.target.checked)}
            />
            <Button type="submit" className="w-full" loading={login.isPending}>
              {t("auth.submit")}
            </Button>
          </form>
        </RuledPanel>
        <p
          aria-hidden="true"
          className="flex items-center gap-3 text-sm text-muted-foreground before:h-px before:flex-1 before:bg-border after:h-px after:flex-1 after:bg-border"
        >
          {t("auth.or")}
        </p>
        <div className="flex flex-col gap-2">
          <Button
            variant="secondary"
            className="w-full"
            loading={magic.isPending}
            disabled={!email}
            onClick={() => magic.mutate()}
          >
            {t("auth.magicLink")}
          </Button>
          {passkeysSupported() ? (
            <Button
              variant="secondary"
              className="w-full"
              loading={passkey.isPending}
              onClick={() => passkey.mutate()}
            >
              {t("passkeys.signIn")}
            </Button>
          ) : null}
          {orgSso.data?.enabled ? (
            <a
              className={secondary}
              href={`${orgSso.data.start_url}?next=${encodeURIComponent(next)}`}
            >
              {t("auth.continueWith", { provider: orgSso.data.name })}
            </a>
          ) : null}
          {providers.data?.map((p) => (
            <a
              key={p.key}
              className={secondary}
              href={`${p.start_url}?next=${encodeURIComponent(next)}`}
            >
              {t("auth.continueWith", { provider: t(`providers.${p.key}`) })}
            </a>
          ))}
        </div>
        {passkey.isError ? <Alert tone="danger">{t("passkeys.failed")}</Alert> : null}
        <div className="flex flex-wrap justify-between gap-x-4 gap-y-2 text-sm">
          <a className={LINK} href="/forgot-password">
            {t("auth.forgot")}
          </a>
          {/* Sign-up is TutorTrack's own: an organisation's sign-in page doesn't offer it. */}
          {brand.isError ? (
            <a className={LINK} href="/signup">
              {t("auth.noAccount")}
            </a>
          ) : null}
        </div>
      </div>
    </PublicLayout>
  );
}

export function MagicLinkPage() {
  const { t } = useTranslation();
  const [mfa, setMfa] = useState(false);
  const token = params().get("token") ?? "";
  const next = safeNext(params().get("next"));
  const verify = useQuery({
    queryKey: ["magic-link", token],
    enabled: !!token,
    retry: false,
    staleTime: Infinity,
    queryFn: async () => {
      const data = unwrap(
        await api.POST("/api/v1/auth/magic-link/verify", { body: { token, remember: false } }),
      );
      if (data.mfa_required) setMfa(true);
      else window.location.assign(next);
      return data;
    },
  });
  return (
    <PublicLayout title={t("auth.signInTitle")}>
      {mfa ? (
        <MFAStep onDone={() => window.location.assign(next)} />
      ) : verify.isError || !token ? (
        <Alert tone="danger">{t("auth.linkInvalid")}</Alert>
      ) : (
        <p role="status">{t("auth.checkingLink")}</p>
      )}
    </PublicLayout>
  );
}

export function ForgotPasswordPage() {
  const { t } = useTranslation();
  const [email, setEmail] = useState("");
  const send = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/v1/auth/password/reset", { body: { email, next: "/" } })),
  });
  return (
    <PublicLayout title={t("auth.forgotTitle")} subtitle={t("auth.forgotBody")}>
      {send.isSuccess ? (
        <Alert tone="success">{t("auth.forgotSent")}</Alert>
      ) : (
        <form
          className="flex flex-col gap-4 rounded-xl border border-border bg-surface p-5"
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            send.mutate();
          }}
        >
          <TextField
            label={t("auth.email")}
            type="email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <Button type="submit" loading={send.isPending}>
            {t("auth.forgotSubmit")}
          </Button>
        </form>
      )}
      <a className={`mt-4 inline-block text-sm ${LINK}`} href="/login">
        {t("auth.backToLogin")}
      </a>
    </PublicLayout>
  );
}

export function ResetPasswordPage() {
  const { t } = useTranslation();
  const [password, setPassword] = useState("");
  const reset = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/auth/password/reset/confirm", {
          body: {
            uid: params().get("uid") ?? "",
            token: params().get("token") ?? "",
            new_password: password,
          },
        }),
      ),
  });
  const error = reset.error as { problem?: { errors?: Record<string, string[]> } } | null;
  return (
    <PublicLayout title={t("auth.resetTitle")}>
      {reset.isSuccess ? (
        <Alert tone="success">
          {t("auth.resetDone")}{" "}
          <a className="underline" href="/login">
            {t("auth.backToLogin")}
          </a>
        </Alert>
      ) : (
        <form
          className="flex flex-col gap-4 rounded-xl border border-border bg-surface p-5"
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            reset.mutate();
          }}
        >
          {reset.isError && !error?.problem?.errors ? (
            <Alert tone="danger">{reset.error.message}</Alert>
          ) : null}
          <TextField
            label={t("auth.newPassword")}
            type="password"
            autoComplete="new-password"
            hint={t("signup.passwordHint")}
            value={password}
            error={error?.problem?.errors?.new_password?.[0]}
            onChange={(e) => setPassword(e.target.value)}
          />
          <Button type="submit" loading={reset.isPending}>
            {t("auth.resetSubmit")}
          </Button>
        </form>
      )}
    </PublicLayout>
  );
}

/** After SSO on the root host: exchange the handoff token for a session here. */
export function ContinuePage() {
  const { t } = useTranslation();
  const token = params().get("handoff") ?? "";
  const next = safeNext(params().get("next"));
  const handoff = useQuery({
    queryKey: ["handoff", token],
    enabled: !!token,
    retry: false,
    staleTime: Infinity,
    queryFn: async () => {
      const data = unwrap(await api.POST("/api/v1/auth/handoff", { body: { token } }));
      window.location.replace(next);
      return data;
    },
  });
  return (
    <PublicLayout title={t("auth.signInTitle")}>
      {handoff.isError || !token ? (
        <Alert tone="danger">
          {t("auth.linkInvalid")}{" "}
          <a className="underline" href="/login">
            {t("auth.backToLogin")}
          </a>
        </Alert>
      ) : (
        <p role="status">{t("auth.checkingLink")}</p>
      )}
    </PublicLayout>
  );
}
