import { unwrap } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  cn,
  FormPanel,
  NamePlate,
  PageHeader,
  PanelRow,
  PanelRows,
  RuledPanel,
  RuledTable,
  SelectField,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, fieldErrors, useMe, usePermission } from "../api";
import { useIsPhone } from "../billing/useIsPhone";

const ROLES = [
  "owner",
  "admin",
  "branch_manager",
  "coordinator",
  "finance",
  "tutor",
  "client",
  "student",
] as const;
const VIEWABLE = new Set(["tutor", "client", "student"]);
const PENDING_SHOWN = 5;

export function TeamPage() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const { data: me } = useMe();
  const canManage = usePermission("team.manage");
  const canInvite = usePermission("team.invite");
  const canImpersonate = usePermission("impersonation.start");
  const roleOptions = ROLES.map((r) => ({ value: r, label: t(`roles.${r}`) }));

  const members = useQuery({
    queryKey: ["memberships"],
    queryFn: async () => unwrap(await api.GET("/api/v1/memberships")),
  });
  const invitations = useQuery({
    queryKey: ["invitations"],
    enabled: canInvite,
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/invitations", { params: { query: { status: "pending" } } })),
  });
  const refresh = () => void queryClient.invalidateQueries();

  const [invite, setInvite] = useState({ email: "", role: "tutor" });
  const send = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/invitations", {
          body: { email: invite.email, role: invite.role as (typeof ROLES)[number] },
        }),
      ),
    onSuccess: () => {
      setInvite({ email: "", role: invite.role });
      refresh();
    },
  });
  const changeRole = useMutation({
    mutationFn: async ({ id, role }: { id: string; role: string }) =>
      unwrap(
        await api.PATCH("/api/v1/memberships/{id}", {
          params: { path: { id } },
          body: { role: role as (typeof ROLES)[number] },
        }),
      ),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: async (id: string) =>
      unwrap(await api.DELETE("/api/v1/memberships/{id}", { params: { path: { id } } })),
    onSuccess: refresh,
  });
  const resend = useMutation({
    mutationFn: async (id: string) =>
      unwrap(await api.POST("/api/v1/invitations/{id}/resend", { params: { path: { id } } })),
    onSuccess: refresh,
  });
  const revoke = useMutation({
    mutationFn: async (id: string) =>
      unwrap(await api.DELETE("/api/v1/invitations/{id}", { params: { path: { id } } })),
    onSuccess: refresh,
  });
  const viewAs = useMutation({
    mutationFn: async (id: string) =>
      unwrap(await api.POST("/api/v1/impersonate", { body: { membership_id: id, write: false } })),
    onSuccess: () => window.location.assign("/"),
  });
  const errors = fieldErrors(send.error);
  const actionError = changeRole.error ?? remove.error;

  const quiet = "text-muted-foreground";
  const phone = useIsPhone();
  const memberRows = members.data?.results ?? [];
  // On phones the row's actions fold under the name instead of a third column.
  const actions = (m: (typeof memberRows)[number], isMe: boolean, folded: boolean) => (
    <>
      {canImpersonate && VIEWABLE.has(m.role) ? (
        <Button
          size="sm"
          variant="ghost"
          className={folded ? "-ml-3" : undefined}
          onClick={() => viewAs.mutate(m.id)}
        >
          {t("team.viewAs")}
        </Button>
      ) : null}
      {canManage && !isMe ? (
        <Button
          size="sm"
          variant="ghost"
          className={cn(quiet, folded && !(canImpersonate && VIEWABLE.has(m.role)) && "-ml-3")}
          onClick={() => remove.mutate(m.id)}
        >
          {t("team.remove")}
        </Button>
      ) : null}
    </>
  );
  const [allPending, setAllPending] = useState(false);
  const pendingAll = invitations.data?.results ?? [];
  const pending = allPending ? pendingAll : pendingAll.slice(0, PENDING_SHOWN);

  return (
    <div>
      <PageHeader title={t("team.title")} description={t("designS9b.team.description")} />
      {actionError ? (
        <Alert tone="danger" className="mb-6">
          {actionError.message}
        </Alert>
      ) : null}
      <div className="max-w-4xl space-y-6">
        <RuledPanel
          flush
          title={t("team.members")}
          aside={
            members.data ? (
              <span className="text-muted-foreground tabular-nums">
                {t("designS9b.team.memberCount", { count: memberRows.length })}
              </span>
            ) : null
          }
        >
          <RuledTable
            caption={t("team.members")}
            loading={members.isPending}
            loadingLabel={t("grid.loading")}
            empty={members.data && !memberRows.length ? t("designS9b.team.noMembers") : undefined}
            columns={[
              { key: "name", header: t("team.name") },
              { key: "role", header: t("team.role"), width: "w-48" },
              ...(phone
                ? []
                : [{ key: "actions", header: t("common.actions", "Actions"), hidden: true }]),
            ]}
          >
            {memberRows.map((m) => {
              const isMe = m.user.id === me?.user.id;
              return (
                <tr key={m.id}>
                  <td className="min-w-48">
                    <NamePlate
                      name={m.user.name}
                      context={<span className="break-all">{m.user.email}</span>}
                    />
                    {phone ? (
                      <div className="mt-1 flex flex-wrap gap-1 empty:hidden">
                        {actions(m, isMe, true)}
                      </div>
                    ) : null}
                  </td>
                  <td className="py-1.5 align-middle">
                    {canManage && !isMe ? (
                      <label>
                        <span className="sr-only">
                          {t("team.role")}: {m.user.name}
                        </span>
                        <select
                          className="h-9 rounded-md border border-field bg-surface px-2 text-sm"
                          value={m.role}
                          onChange={(e) => changeRole.mutate({ id: m.id, role: e.target.value })}
                        >
                          {roleOptions.map((o) => (
                            <option key={o.value} value={o.value}>
                              {o.label}
                            </option>
                          ))}
                        </select>
                      </label>
                    ) : (
                      t(`roles.${m.role}`)
                    )}
                  </td>
                  {phone ? null : (
                    <td className="py-1.5 text-right align-middle whitespace-nowrap">
                      {actions(m, isMe, false)}
                    </td>
                  )}
                </tr>
              );
            })}
          </RuledTable>
        </RuledPanel>
        {canInvite ? (
          <>
            <FormPanel
              title={t("team.invite")}
              submit={t("team.inviteSubmit")}
              pending={send.isPending}
              onSubmit={() => send.mutate()}
              error={
                send.isSuccess ? (
                  <Alert tone="success">{t("team.invited", { email: send.data.email })}</Alert>
                ) : send.isError && Object.keys(errors).length === 0 ? (
                  <Alert tone="danger">{send.error.message}</Alert>
                ) : null
              }
            >
              <TextField
                label={t("team.email")}
                type="email"
                value={invite.email}
                error={errors.email}
                onChange={(e) => setInvite((i) => ({ ...i, email: e.target.value }))}
              />
              <SelectField
                label={t("team.role")}
                value={invite.role}
                options={roleOptions}
                onChange={(e) => setInvite((i) => ({ ...i, role: e.target.value }))}
              />
            </FormPanel>
            {pendingAll.length ? (
              <RuledPanel
                flush
                title={t("team.pending")}
                footer={
                  pendingAll.length > PENDING_SHOWN ? (
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-expanded={allPending}
                      className="-ml-3 text-link"
                      onClick={() => setAllPending((v) => !v)}
                    >
                      {allPending
                        ? t("designS9b.account.showFewer")
                        : t("designS9b.account.showAll", { count: pendingAll.length })}
                    </Button>
                  ) : null
                }
                aside={
                  <span className="text-muted-foreground tabular-nums">{pendingAll.length}</span>
                }
              >
                <PanelRows>
                  {pending.map((inv) => (
                    <PanelRow key={inv.id}>
                      <NamePlate
                        name={<span className="break-all">{inv.email}</span>}
                        context={
                          <span className="tabular-nums">
                            {t(`roles.${inv.role}`)} ·{" "}
                            {t("team.expires", {
                              when: formatDateTime(inv.expires_at, i18n.language),
                            })}
                          </span>
                        }
                        aside={
                          <>
                            <Button
                              size="sm"
                              variant="ghost"
                              className="max-sm:-ml-3"
                              onClick={() => resend.mutate(inv.id)}
                            >
                              {t("team.resend")}
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              className={quiet}
                              onClick={() => revoke.mutate(inv.id)}
                            >
                              {t("team.revoke")}
                            </Button>
                          </>
                        }
                      />
                    </PanelRow>
                  ))}
                </PanelRows>
              </RuledPanel>
            ) : null}
          </>
        ) : null}
      </div>
    </div>
  );
}
