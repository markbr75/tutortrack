import { unwrap } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { api, fieldErrors, useMe, usePermission } from "../api";

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

  return (
    <div>
      <h1 className="text-2xl font-semibold">{t("team.title")}</h1>
      {actionError ? (
        <Alert tone="danger" className="mt-4">
          {actionError.message}
        </Alert>
      ) : null}
      <section className="mt-6 overflow-x-auto">
        <h2 className="text-lg font-medium">{t("team.members")}</h2>
        <table className="mt-2 w-full text-left text-sm">
          <thead className="text-muted-foreground">
            <tr>
              <th scope="col" className="py-2">
                {t("team.name")}
              </th>
              <th scope="col">{t("team.role")}</th>
              <th scope="col">
                <span className="sr-only">{t("common.actions", "Actions")}</span>
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {members.data?.results.map((m) => {
              const isMe = m.user.id === me?.user.id;
              return (
                <tr key={m.id}>
                  <td className="py-2">
                    <span className="block font-medium">{m.user.name}</span>
                    <span className="text-muted-foreground">{m.user.email}</span>
                  </td>
                  <td>
                    {canManage && !isMe ? (
                      <label>
                        <span className="sr-only">
                          {t("team.role")}: {m.user.name}
                        </span>
                        <select
                          className="h-9 rounded-md border border-border bg-background px-2"
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
                  <td className="text-right whitespace-nowrap">
                    {canImpersonate && VIEWABLE.has(m.role) ? (
                      <Button size="sm" variant="ghost" onClick={() => viewAs.mutate(m.id)}>
                        {t("team.viewAs")}
                      </Button>
                    ) : null}
                    {canManage && !isMe ? (
                      <Button size="sm" variant="ghost" onClick={() => remove.mutate(m.id)}>
                        {t("team.remove")}
                      </Button>
                    ) : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>

      {canInvite ? (
        <>
          <section className="mt-8 max-w-2xl">
            <h2 className="text-lg font-medium">{t("team.invite")}</h2>
            {send.isSuccess ? (
              <Alert tone="success" className="mt-2">
                {t("team.invited", { email: send.data.email })}
              </Alert>
            ) : null}
            {send.isError && Object.keys(errors).length === 0 ? (
              <Alert tone="danger" className="mt-2">
                {send.error.message}
              </Alert>
            ) : null}
            <form
              className="mt-2 grid gap-3 sm:grid-cols-[1fr_12rem_auto] sm:items-end"
              onSubmit={(e: FormEvent) => {
                e.preventDefault();
                send.mutate();
              }}
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
              <Button type="submit" loading={send.isPending}>
                {t("team.inviteSubmit")}
              </Button>
            </form>
          </section>
          {invitations.data?.results.length ? (
            <section className="mt-8 max-w-2xl">
              <h2 className="text-lg font-medium">{t("team.pending")}</h2>
              <ul className="mt-2 divide-y divide-border">
                {invitations.data.results.map((inv) => (
                  <li key={inv.id} className="flex items-center justify-between py-2 text-sm">
                    <span>
                      {inv.email} · {t(`roles.${inv.role}`)}
                      <span className="block text-muted-foreground">
                        {t("team.expires", {
                          when: formatDateTime(inv.expires_at, i18n.language),
                        })}
                      </span>
                    </span>
                    <span className="whitespace-nowrap">
                      <Button size="sm" variant="ghost" onClick={() => resend.mutate(inv.id)}>
                        {t("team.resend")}
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => revoke.mutate(inv.id)}>
                        {t("team.revoke")}
                      </Button>
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
