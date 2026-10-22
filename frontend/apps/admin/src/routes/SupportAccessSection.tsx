import { unwrap } from "@tutortrack/api-client";
import { formatDate, formatDateTime, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  CheckboxField,
  PanelRow,
  PanelRows,
  RuledPanel,
  UnitField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, usePermission } from "../api";

/** When TutorTrack support viewed the account, and grants for them to do so (E30 FR-30-2). */
export function SupportAccessSection() {
  const { t, i18n } = useTranslation();
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
    <RuledPanel
      flush
      titleId="support-access"
      title={t("support.title")}
      description={
        access.data.requires_grant ? t("support.requiresGrant") : t("support.readOnlyDefault")
      }
    >
      {active.length || access.data.sessions.length ? (
        <PanelRows>
          {active.map((g) => (
            <PanelRow key={g.id} className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-medium tabular-nums">
                {t(g.allow_write ? "support.grantWrite" : "support.grantRead", {
                  date: formatDate(g.expires_at, i18n.language),
                })}
              </span>
              {canManage ? (
                <Button
                  size="sm"
                  variant="ghost"
                  className="text-muted-foreground"
                  onClick={() => revoke.mutate(g.id)}
                >
                  {t("support.revoke")}
                </Button>
              ) : null}
            </PanelRow>
          ))}
          {access.data.sessions.map((s) => (
            <PanelRow key={s.id} className="tabular-nums">
              {t("support.session", {
                date: formatDateTime(s.created_at, i18n.language),
                name: s.staff_name,
                email: s.viewed_as,
                reason: s.reason,
              })}
            </PanelRow>
          ))}
        </PanelRows>
      ) : null}
      {!access.data.sessions.length ? (
        <p
          className={`px-5 py-4 text-sm text-muted-foreground ${active.length ? "border-t border-rule" : ""}`}
        >
          {t("support.noSessions")}
        </p>
      ) : null}
      {canManage ? (
        <form
          aria-label={t("support.grant")}
          className="flex flex-wrap items-end gap-x-4 gap-y-3 border-t border-rule px-5 py-3"
          onSubmit={(e) => {
            e.preventDefault();
            grant.mutate();
          }}
        >
          <UnitField
            label={t("support.days")}
            hideLabel
            size="sm"
            unit={t("designS9b.units.days")}
            min={1}
            max={30}
            value={days}
            onChange={(e) => setDays(e.target.value)}
          />
          <CheckboxField
            className="h-9 justify-center"
            label={t("support.allowWrite")}
            checked={allowWrite}
            onChange={(e) => setAllowWrite(e.target.checked)}
          />
          <Button type="submit" size="sm" className="h-9" loading={grant.isPending}>
            {t("support.grant")}
          </Button>
          {grant.error ? (
            <Alert tone="danger" className="basis-full">
              {grant.error.message}
            </Alert>
          ) : null}
        </form>
      ) : null}
    </RuledPanel>
  );
}
