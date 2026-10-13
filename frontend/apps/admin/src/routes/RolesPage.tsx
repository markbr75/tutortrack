import { unwrap, type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, Button, ErrorFallback, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState, type FormEvent } from "react";

import { api, fieldErrors, usePermission } from "../api";

type CustomRole = components["schemas"]["CustomRole"];
const STAFF_BASES = ["admin", "branch_manager", "coordinator", "finance", "tutor"] as const;
const SCOPES = ["none", "own", "branch", "all"] as const;
const STAFF_MEMBERS = new Set(["admin", "branch_manager", "coordinator", "finance", "tutor"]);

/** Custom roles and the permission matrix (FR-03-5, E03-T11): clone a built-in staff role,
 * choose a scope per permission, and give the role to team members (their permissions are
 * the union of their custom roles). */
export function RolesPage() {
  const { t } = useTranslation();
  const canManage = usePermission("team.roles.manage");
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<string | null>(null);
  const [draft, setDraft] = useState({ name: "", clone_from: "coordinator" });
  const roles = useQuery({
    queryKey: ["custom-roles"],
    queryFn: async () => unwrap(await api.GET("/api/v1/custom-roles")),
  });
  const create = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/custom-roles", { body: draft })),
    onSuccess: (role) => {
      setDraft({ name: "", clone_from: "coordinator" });
      setSelected(role.id);
      void queryClient.invalidateQueries({ queryKey: ["custom-roles"] });
    },
  });
  if (roles.isError) {
    return (
      <ErrorFallback
        title={t("errors.generic")}
        retryLabel={t("errors.retry")}
        onRetry={() => void roles.refetch()}
      />
    );
  }
  if (roles.isPending) return <Spinner label={t("grid.loading")} />;
  const current = roles.data.find((r) => r.id === selected) ?? null;
  return (
    <section className="space-y-6">
      <h1 className="text-2xl font-semibold">{t("customRoles.title")}</h1>
      <p className="max-w-3xl text-sm text-muted-foreground">{t("customRoles.intro")}</p>
      <ul className="flex flex-wrap gap-2" aria-label={t("customRoles.list")}>
        {roles.data.map((role) => (
          <li key={role.id}>
            <Button
              size="sm"
              variant={role.id === selected ? "primary" : "secondary"}
              aria-pressed={role.id === selected}
              onClick={() => setSelected(role.id)}
            >
              {role.name} ({role.members})
            </Button>
          </li>
        ))}
      </ul>
      {canManage ? (
        <form
          className="flex flex-wrap items-end gap-3 rounded-lg border border-border p-4"
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <TextField
            label={t("customRoles.name")}
            value={draft.name}
            onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            required
          />
          <SelectField
            label={t("customRoles.cloneFrom")}
            value={draft.clone_from}
            onChange={(e) => setDraft({ ...draft, clone_from: e.target.value })}
            options={STAFF_BASES.map((key) => ({ value: key, label: t(`roles.${key}`) }))}
          />
          <Button type="submit" disabled={create.isPending}>
            {t("customRoles.create")}
          </Button>
          {create.error ? (
            <Alert tone="danger">
              {Object.values(fieldErrors(create.error)).join(" ") || t("errors.generic")}
            </Alert>
          ) : null}
        </form>
      ) : null}
      {current ? <RoleEditor key={current.id} role={current} canManage={canManage} /> : null}
    </section>
  );
}

function RoleEditor({ role, canManage }: { role: CustomRole; canManage: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [changes, setChanges] = useState<Record<string, string>>({});
  const permissions = useQuery({
    queryKey: ["permissions"],
    queryFn: async () => unwrap(await api.GET("/api/v1/permissions")),
  });
  const members = useQuery({
    queryKey: ["memberships"],
    queryFn: async () => unwrap(await api.GET("/api/v1/memberships")),
  });
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PATCH("/api/v1/custom-roles/{id}", {
          params: { path: { id: role.id } },
          body: { grants: changes as Record<string, (typeof SCOPES)[number]> },
        }),
      ),
    onSuccess: () => {
      setChanges({});
      void queryClient.invalidateQueries({ queryKey: ["custom-roles"] });
    },
  });
  const assign = useMutation({
    mutationFn: async ({ id, roles }: { id: string; roles: string[] }) =>
      unwrap(
        await api.PATCH("/api/v1/memberships/{id}", {
          params: { path: { id } },
          body: { custom_roles: roles },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["memberships"] });
      void queryClient.invalidateQueries({ queryKey: ["custom-roles"] });
    },
  });
  const archive = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/custom-roles/{id}/archive", { params: { path: { id: role.id } } }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["custom-roles"] }),
  });
  const grouped = useMemo(() => {
    const out: Record<string, { codename: string; description: string }[]> = {};
    for (const p of permissions.data ?? []) (out[p.category] ??= []).push(p);
    return Object.entries(out);
  }, [permissions.data]);
  const scopeOf = (codename: string) => changes[codename] ?? role.grants[codename] ?? "none";
  return (
    <section className="space-y-4" aria-labelledby="role-heading">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="role-heading" className="text-xl font-semibold">
          {role.name}
        </h2>
        {canManage ? (
          <div className="flex gap-2">
            <Button onClick={() => save.mutate()} disabled={!Object.keys(changes).length}>
              {t("customRoles.save")}
            </Button>
            <Button variant="secondary" onClick={() => archive.mutate()}>
              {t("customRoles.archive")}
            </Button>
          </div>
        ) : null}
      </div>
      {save.isSuccess ? <Alert tone="success">{t("customRoles.saved")}</Alert> : null}
      <div className="space-y-4">
        {grouped.map(([category, perms]) => (
          <fieldset key={category} className="rounded-lg border border-border p-3">
            <legend className="px-1 font-medium">{category}</legend>
            <table className="w-full text-sm">
              <caption className="sr-only">{t("customRoles.matrixFor", { category })}</caption>
              <thead>
                <tr>
                  <th scope="col" className="text-left">
                    {t("customRoles.permission")}
                  </th>
                  <th scope="col" className="w-40 text-left">
                    {t("customRoles.scope")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {perms.map((p) => (
                  <tr key={p.codename} className="border-t border-border">
                    <td className="py-1">
                      {p.description} <code className="text-xs">{p.codename}</code>
                    </td>
                    <td className="py-1">
                      <select
                        aria-label={t("customRoles.scopeFor", { permission: p.description })}
                        className="rounded border border-border bg-background px-2 py-1"
                        value={scopeOf(p.codename)}
                        disabled={!canManage}
                        onChange={(e) => setChanges({ ...changes, [p.codename]: e.target.value })}
                      >
                        {SCOPES.map((scope) => (
                          <option key={scope} value={scope}>
                            {t(`customRoles.scopes.${scope}`)}
                          </option>
                        ))}
                      </select>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </fieldset>
        ))}
      </div>
      <fieldset className="rounded-lg border border-border p-3">
        <legend className="px-1 font-medium">{t("customRoles.members")}</legend>
        <ul className="space-y-1">
          {(members.data?.results ?? [])
            .filter((m) => STAFF_MEMBERS.has(m.role))
            .map((m) => {
              const has = m.custom_roles.includes(role.id);
              return (
                <li key={m.id}>
                  <label className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={has}
                      disabled={!canManage}
                      onChange={() =>
                        assign.mutate({
                          id: m.id,
                          roles: has
                            ? m.custom_roles.filter((r) => r !== role.id)
                            : [...m.custom_roles, role.id],
                        })
                      }
                    />
                    {m.user.email} · {t(`roles.${m.role}`)}
                  </label>
                </li>
              );
            })}
        </ul>
        {assign.error ? (
          <Alert tone="danger">
            {Object.values(fieldErrors(assign.error)).join(" ") || t("errors.generic")}
          </Alert>
        ) : null}
      </fieldset>
    </section>
  );
}
