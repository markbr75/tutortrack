import { unwrap } from "@tutortrack/api-client";
import { formatDate, formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, usePermission } from "../api";

/** When TutorTrack support viewed the account, and grants for them to do so (E30 FR-30-2). */
export function SupportAccessSection() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canView = usePermission("support.access.view");
  const canManage = usePermission("support.access.manage");
  const [days, setDays] = useState("7");
  const [allowWrite, setAllowWrite] = useState(false);
  const access = useQuery({
    queryKey: ["support-access"],
    queryFn: async () => unwrap(await api.GET("/api/v1/support-access")),
    enabled: canView,
  });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["support-access"] });
  const grant = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/support-access/grants", {
          body: { days: Number(days), allow_write: allowWrite, note: "" },
        }),
      ),
    onSuccess: refresh,
  });
  const revoke = useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.POST("/api/v1/support-access/grants/{id}/revoke", { params: { path: { id } } }),
      ),
    onSuccess: refresh,
  });
  if (!canView || !access.data) return null;
  const active = access.data.grants.filter((g) => g.active);
  return (
    <section aria-labelledby="support-access" className="mt-8 space-y-3">
      <h2 id="support-access" className="text-lg font-semibold">
        {t("support.title")}
      </h2>
      <p className="text-sm text-muted-foreground">
        {access.data.requires_grant ? t("support.requiresGrant") : t("support.readOnlyDefault")}
      </p>
      {active.map((g) => (
        <p key={g.id} className="flex flex-wrap items-center gap-2 text-sm">
          {t(g.allow_write ? "support.grantWrite" : "support.grantRead", {
            date: formatDate(g.expires_at),
          })}
          {canManage ? (
            <Button size="sm" variant="ghost" onClick={() => revoke.mutate(g.id)}>
              {t("support.revoke")}
            </Button>
          ) : null}
        </p>
      ))}
      {canManage ? (
        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            grant.mutate();
          }}
        >
          <TextField
            label={t("support.days")}
            type="number"
            min={1}
            max={30}
            value={days}
            onChange={(e) => setDays(e.target.value)}
            className="w-24"
          />
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={allowWrite}
              onChange={(e) => setAllowWrite(e.target.checked)}
            />
            {t("support.allowWrite")}
          </label>
          <Button type="submit" size="sm" loading={grant.isPending}>
            {t("support.grant")}
          </Button>
        </form>
      ) : null}
      {grant.error ? <Alert tone="danger">{grant.error.message}</Alert> : null}
      {access.data.sessions.length ? (
        <ul className="space-y-1 text-sm">
          {access.data.sessions.map((s) => (
            <li key={s.id}>
              {t("support.session", {
                date: formatDateTime(s.created_at),
                name: s.staff_name,
                email: s.viewed_as,
                reason: s.reason,
              })}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm">{t("support.noSessions")}</p>
      )}
    </section>
  );
}
