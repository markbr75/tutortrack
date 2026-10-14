import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, Button, TextField } from "@tutortrack/ui";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api";
import { getPasskey, passkeysSupported } from "../routes/webauthn";

/** Confirm it's you (password, authenticator code or passkey) before sensitive details
 * such as full bank details (E12 §6, gap G3). Calls ``onDone`` once confirmed. */
export function ReauthPrompt({ onDone, onCancel }: { onDone: () => void; onCancel: () => void }) {
  const { t } = useTranslation();
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const status = useQuery({
    queryKey: ["reauth"],
    queryFn: async () => unwrap(await api.GET("/api/v1/auth/reauthenticate")),
  });
  const methods = status.data?.methods ?? ["password"];
  const confirm = useMutation({
    mutationFn: async (body: { password?: string; code?: string; credential?: unknown }) =>
      unwrap(
        await api.POST("/api/v1/auth/reauthenticate", {
          body: body as { password: string; code: string },
        }),
      ),
    onSuccess: onDone,
  });
  const passkey = useMutation({
    mutationFn: async () => {
      const options = unwrap(await api.POST("/api/v1/auth/reauthenticate/options"));
      const credential = await getPasskey(options as never);
      return unwrap(
        await api.POST("/api/v1/auth/reauthenticate", {
          body: { credential } as never,
        }),
      );
    },
    onSuccess: onDone,
  });
  return (
    <form
      className="mt-3 space-y-2 rounded-md border border-border p-3"
      aria-label={t("g3.reauth.title")}
      onSubmit={(e) => {
        e.preventDefault();
        confirm.mutate(code ? { code } : { password });
      }}
    >
      <p className="text-sm font-medium">{t("g3.reauth.title")}</p>
      <p className="text-xs text-muted-foreground">{t("g3.reauth.help")}</p>
      {methods.includes("password") ? (
        <TextField
          label={t("g3.reauth.password")}
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      ) : null}
      {methods.includes("totp") ? (
        <TextField
          label={t("g3.reauth.code")}
          inputMode="numeric"
          autoComplete="one-time-code"
          value={code}
          onChange={(e) => setCode(e.target.value)}
        />
      ) : null}
      {confirm.isError || passkey.isError ? (
        <Alert tone="danger">{t("g3.reauth.failed")}</Alert>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" size="sm" disabled={confirm.isPending || (!password && !code)}>
          {t("g3.reauth.confirm")}
        </Button>
        {methods.includes("passkey") && passkeysSupported() ? (
          <Button type="button" size="sm" variant="secondary" onClick={() => passkey.mutate()}>
            {t("g3.reauth.passkey")}
          </Button>
        ) : null}
        <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
          {t("g3.reauth.cancel")}
        </Button>
      </div>
    </form>
  );
}
