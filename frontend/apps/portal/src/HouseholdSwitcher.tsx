import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Button, TextField } from "@tutortrack/ui";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { api, type PortalMe } from "./api";

/** Pick which household the portal shows, for people linked to several (FR-15-1). */
export function HouseholdSwitcher({ me }: { me: PortalMe }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const id = useId();
  const choose = useMutation({
    mutationFn: async (clientId: string) =>
      unwrap(await api.POST("/api/v1/portal/household", { body: { client_id: clientId } })),
    onSuccess: () => void queryClient.invalidateQueries(),
  });
  // Older API responses (and test fixtures) may not list households yet.
  const households = (me.households as PortalMe["households"] | undefined) ?? [];
  if (households.length < 2) return null;
  return (
    <div className="flex items-center gap-2 text-sm">
      <label htmlFor={id}>{t("family.household")}</label>
      <select
        id={id}
        className="rounded-md border border-border bg-background px-2 py-1"
        value={me.household ?? ""}
        disabled={choose.isPending}
        onChange={(e) => choose.mutate(e.target.value)}
      >
        <option value="">{t("family.allHouseholds")}</option>
        {households.map((h) => (
          <option key={h.id} value={h.id}>
            {h.name}
          </option>
        ))}
      </select>
    </div>
  );
}

/** Children under 13 sign in with the username and PIN their guardian set (FR-15-1). */
export function StudentSignIn() {
  const { t } = useTranslation();
  const [username, setUsername] = useState("");
  const [pin, setPin] = useState("");
  const signIn = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/v1/auth/student-login", { body: { username, pin } })),
    onSuccess: () => window.location.assign("/portal/"),
  });
  return (
    <form
      className="space-y-3"
      aria-label={t("family.childSignIn")}
      onSubmit={(e) => {
        e.preventDefault();
        signIn.mutate();
      }}
    >
      <h2 className="text-lg font-medium">{t("family.childSignIn")}</h2>
      <TextField
        label={t("family.username")}
        autoComplete="username"
        autoCapitalize="none"
        required
        value={username}
        onChange={(e) => setUsername(e.target.value)}
      />
      <TextField
        label={t("family.pin")}
        type="password"
        autoComplete="current-password"
        required
        value={pin}
        onChange={(e) => setPin(e.target.value)}
      />
      {signIn.isError ? (
        <p role="alert" className="text-sm text-destructive">
          {signIn.error.message}
        </p>
      ) : null}
      <Button type="submit" variant="secondary" loading={signIn.isPending}>
        {t("family.childSignInButton")}
      </Button>
    </form>
  );
}
