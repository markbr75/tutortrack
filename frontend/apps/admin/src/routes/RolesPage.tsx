import { unwrap, type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  CheckboxField,
  Disclosure,
  ErrorFallback,
  FormPanel,
  PageHeader,
  PanelFooter,
  RuledPanel,
  SelectField,
  Spinner,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { api, fieldErrors, usePermission } from "../api";
import { SavedNote } from "../components/SavedNote";

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
    <div className="max-w-4xl">
      <PageHeader title={t("customRoles.title")} description={t("customRoles.intro")} />
      <div className="space-y-6">
        <div className="grid grid-cols-[minmax(0,1fr)] items-start gap-6 lg:grid-cols-2">
          <RuledPanel
            flush
            title={t("customRoles.list")}
            description={roles.data.length && !current ? t("designS9b.roles.choose") : undefined}
          >
            {roles.data.length ? (
              <ul aria-label={t("customRoles.list")} className="divide-y divide-rule">
                {roles.data.map((role) => (
                  <li key={role.id}>
                    <button
                      type="button"
                      aria-pressed={role.id === selected}
                      onClick={() => setSelected(role.id)}
                      className="block w-full px-5 py-2.5 text-left text-sm hover:bg-muted/60 aria-pressed:bg-muted"
                    >
                      <span className="block font-medium">{role.name}</span>
                      <span className="block text-xs text-muted-foreground tabular-nums">
                        {t("designS9b.roles.memberCount", { count: role.members })}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="px-5 py-4 text-sm text-muted-foreground">
                {canManage ? t("designS9b.roles.emptyCanCreate") : t("designS9b.roles.empty")}
              </p>
            )}
          </RuledPanel>
          {canManage ? (
            <FormPanel
              title={t("designS9b.roles.newRole")}
              submit={t("customRoles.create")}
              pending={create.isPending}
              onSubmit={() => create.mutate()}
              columns={1}
              error={
                create.error ? (
                  <Alert tone="danger">
                    {Object.values(fieldErrors(create.error)).join(" ") || t("errors.generic")}
                  </Alert>
                ) : null
              }
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
            </FormPanel>
          ) : null}
        </div>
        {current ? <RoleEditor key={current.id} role={current} canManage={canManage} /> : null}
      </div>
    </div>
  );
}

function RoleEditor({ role, canManage }: { role: CustomRole; canManage: boolean }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [changes, setChanges] = useState<Record<string, string>>({});
  // Areas changed in this visit stay open, also after saving.
  const [touched, setTouched] = useState<Set<string>>(() => new Set());
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
    // Areas in the order of their names, as people read them.
    const name = (key: string) => t(`designS9b.roles.categories.${key}`, key);
    return Object.entries(out).sort(([a], [b]) => name(a).localeCompare(name(b)));
  }, [permissions.data, t]);
  const scopeOf = (codename: string) => changes[codename] ?? role.grants[codename] ?? "none";
  const staff = (members.data?.results ?? []).filter((m) => STAFF_MEMBERS.has(m.role));
  const changed = Object.keys(changes).length;
  return (
    <section className="space-y-6" aria-labelledby="role-heading">
      <RuledPanel
        flush
        titleId="role-heading"
        title={role.name}
        description={t("designS9b.roles.openArea")}
        aside={
          <span className="text-muted-foreground tabular-nums">
            {t("designS9b.roles.memberCount", { count: role.members })}
          </span>
        }
      >
        {permissions.isPending ? (
          <div className="px-5 py-4">
            <Spinner label={t("grid.loading")} />
          </div>
        ) : null}
        <ul className="divide-y divide-rule">
          {grouped.map(([category, perms]) => {
            const name = t(`designS9b.roles.categories.${category}`, category);
            const allowed = perms.filter((p) => scopeOf(p.codename) !== "none").length;
            const pending = perms.some((p) => p.codename in changes) || touched.has(category);
            return (
              <li key={category}>
                {/* Closed by default; an area with unsaved changes is kept open. */}
                <Disclosure
                  open={pending || undefined}
                  summaryClassName="w-full px-5 py-3"
                  bodyClassName="mt-0"
                  summary={
                    <>
                      <span className="min-w-0 flex-1">{name}</span>
                      <span className="font-normal text-muted-foreground tabular-nums">
                        {t("designS9b.roles.allowed", { allowed, total: perms.length })}
                      </span>
                    </>
                  }
                >
                  <table className="mb-2 w-full text-sm">
                    <caption className="sr-only">
                      {t("customRoles.matrixFor", { category: name })}
                    </caption>
                    <thead className="sr-only">
                      <tr>
                        <th scope="col">{t("customRoles.permission")}</th>
                        <th scope="col">{t("customRoles.scope")}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {perms.map((p) => (
                        <tr key={p.codename}>
                          <td className="py-1.5 pr-4 pl-10 align-middle">
                            {/* The permission's code name is kept as a tooltip, for the guides. */}
                            <span title={p.codename}>{p.description}</span>
                          </td>
                          <td className="w-40 py-1.5 pr-5 align-middle sm:w-48">
                            <select
                              aria-label={t("customRoles.scopeFor", {
                                permission: p.description,
                              })}
                              className="h-9 w-full rounded-md border border-field bg-surface px-2 text-sm"
                              value={scopeOf(p.codename)}
                              disabled={!canManage}
                              onChange={(e) => {
                                setChanges({ ...changes, [p.codename]: e.target.value });
                                setTouched((all) => new Set(all).add(category));
                              }}
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
                </Disclosure>
              </li>
            );
          })}
        </ul>
        {canManage ? (
          <PanelFooter className="border-border">
            <Button onClick={() => save.mutate()} disabled={!changed} loading={save.isPending}>
              {t("customRoles.save")}
            </Button>
            <SavedNote show={save.isSuccess && !changed} text={t("customRoles.saved")} />
            {changed ? (
              <span className="text-muted-foreground tabular-nums" aria-live="polite">
                {t("designS9b.roles.unsaved", { count: changed })}
              </span>
            ) : null}
            <Button
              variant="ghost"
              size="sm"
              className="ml-auto text-muted-foreground"
              loading={archive.isPending}
              onClick={() => archive.mutate()}
            >
              {t("customRoles.archive")}
            </Button>
          </PanelFooter>
        ) : null}
      </RuledPanel>
      <RuledPanel flush title={t("customRoles.members")}>
        {staff.length ? (
          <ul className="divide-y divide-rule">
            {staff.map((m) => {
              const has = m.custom_roles.includes(role.id);
              return (
                <li key={m.id} className="px-5 py-2.5">
                  <CheckboxField
                    checked={has}
                    disabled={!canManage}
                    label={`${m.user.email} · ${t(`roles.${m.role}`)}`}
                    onChange={() =>
                      assign.mutate({
                        id: m.id,
                        roles: has
                          ? m.custom_roles.filter((r) => r !== role.id)
                          : [...m.custom_roles, role.id],
                      })
                    }
                  />
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="px-5 py-4 text-sm text-muted-foreground">{t("designS9b.roles.noStaff")}</p>
        )}
        {assign.error ? (
          <div className="px-5 pb-4">
            <Alert tone="danger">
              {Object.values(fieldErrors(assign.error)).join(" ") || t("errors.generic")}
            </Alert>
          </div>
        ) : null}
      </RuledPanel>
    </section>
  );
}
