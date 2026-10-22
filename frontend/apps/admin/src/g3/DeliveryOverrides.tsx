import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Button, Panel, PanelRow, PanelRows, SelectField, Spinner } from "@tutortrack/ui";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api";
import { PolicyForm } from "../delivery/DeliverySettingsPage";

type Scope = "branch" | "service" | "job" | "client";
const SCOPES: Scope[] = ["branch", "service", "job", "client"];

/** Records a policy can be set for, as ``{id, name}`` (first 200 of each kind). */
function useScopeRecords(scope: Scope) {
  return useQuery({
    queryKey: ["g3", "policy-scope", scope],
    queryFn: async (): Promise<{ id: string; name: string }[]> => {
      if (scope === "branch") {
        const page = unwrap(await api.GET("/api/v1/branches"));
        return page.results.map((b) => ({ id: b.id, name: b.name }));
      }
      if (scope === "service") {
        const page = unwrap(await api.GET("/api/v1/catalogue/services"));
        return page.results.map((s) => ({ id: s.id, name: s.name }));
      }
      if (scope === "job") {
        const page = unwrap(
          await api.GET("/api/v1/jobs", { params: { query: { page_size: 200 } } }),
        );
        return page.results.map((j) => ({ id: j.id, name: `${j.reference} · ${j.name}` }));
      }
      const page = unwrap(
        await api.GET("/api/v1/clients", { params: { query: { page_size: 200 } } }),
      );
      return page.results.map((c) => ({ id: c.id, name: c.display_name }));
    },
  });
}

/** Cancellation policy overrides for a branch, service, job or client (FR-09-3, gap G3):
 * the most specific active policy wins. */
export function PolicyOverrides() {
  const { t } = useTranslation();
  const [scope, setScope] = useState<Scope>("service");
  const [record, setRecord] = useState("");
  const records = useScopeRecords(scope);
  const policies = useQuery({
    queryKey: ["cancellation-policies"],
    queryFn: async () => unwrap(await api.GET("/api/v1/cancellation-policies")),
  });
  const overrides = (policies.data ?? []).filter((p) => p.scope_type !== "organisation");
  const chosenName = records.data?.find((r) => r.id === record)?.name ?? "";
  return (
    <div className="space-y-6">
      <Panel title={t("g3.delivery.overrides")} flush>
        <p className="border-b border-rule px-5 py-2.5 text-xs text-muted-foreground">
          {t("g3.delivery.overridesHelp")}
        </p>
        {policies.isPending ? (
          <div className="px-5 py-4">
            <Spinner label={t("grid.loading")} />
          </div>
        ) : overrides.length ? (
          <PanelRows>
            {overrides.map((p) => (
              <PanelRow key={p.id} className="flex items-center justify-between gap-3">
                <span className="min-w-0">
                  <span className="block font-medium">{p.name}</span>
                  <span className="block text-xs text-muted-foreground">
                    {t(`g3.delivery.scopes.${p.scope_type}`)}
                  </span>
                </span>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => {
                    setScope(p.scope_type as Scope);
                    setRecord(p.scope_id ?? "");
                  }}
                >
                  {t("g3.delivery.edit")}
                  <span className="sr-only"> {p.name}</span>
                </Button>
              </PanelRow>
            ))}
          </PanelRows>
        ) : (
          <p className="px-5 py-4 text-sm text-muted-foreground">{t("g3.delivery.noOverrides")}</p>
        )}
      </Panel>
      <section aria-labelledby="override-edit" className="space-y-4">
        <h2 id="override-edit" className="text-base font-semibold">
          {t("g3.delivery.setOverride")}
        </h2>
        <div className="grid max-w-xl gap-3 sm:grid-cols-2">
          <SelectField
            label={t("g3.delivery.scope")}
            value={scope}
            onChange={(e) => {
              setScope(e.target.value as Scope);
              setRecord("");
            }}
            options={SCOPES.map((s) => ({ value: s, label: t(`g3.delivery.scopes.${s}`) }))}
          />
          <SelectField
            label={t(`g3.delivery.scopes.${scope}`)}
            value={record}
            onChange={(e) => setRecord(e.target.value)}
            options={[
              { value: "", label: t("g3.delivery.chooseRecord") },
              ...(records.data ?? []).map((r) => ({ value: r.id, label: r.name })),
            ]}
          />
        </div>
        {record ? (
          <PolicyForm
            key={`${scope}-${record}`}
            scopeType={scope}
            scopeId={record}
            scopeName={t("g3.delivery.overrideName", {
              scope: t(`g3.delivery.scopes.${scope}`),
              name: chosenName,
            })}
          />
        ) : null}
      </section>
    </div>
  );
}

/** Which services, subjects and jobs use a report template (FR-09-4 resolution: job →
 * service → subject → default), edited on the template (gap G3). */
export function TemplateAssignments({
  value,
  onChange,
}: {
  value: { services: string[]; subjects: string[]; jobs: string[] };
  onChange: (value: { services: string[]; subjects: string[]; jobs: string[] }) => void;
}) {
  const { t } = useTranslation();
  const services = useScopeRecords("service");
  const jobs = useScopeRecords("job");
  const subjects = useQuery({
    queryKey: ["g3", "subjects"],
    queryFn: async () => {
      const rows = unwrap(await api.GET("/api/v1/catalogue/subjects"));
      return ("results" in rows ? rows.results : rows) as { id: string; name: string }[];
    },
  });
  const pick = (
    name: "services" | "subjects" | "jobs",
    label: string,
    rows: { id: string; name: string }[] | undefined,
  ) => (
    <fieldset className="space-y-1">
      <legend className="text-sm font-medium">{label}</legend>
      <div className="relative max-h-40 space-y-1.5 overflow-y-auto rounded-md border border-field bg-surface p-2.5">
        {(rows ?? []).map((r) => (
          <label key={r.id} className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              className="mt-0.5 size-4 shrink-0"
              checked={value[name].includes(r.id)}
              onChange={(e) =>
                onChange({
                  ...value,
                  [name]: e.target.checked
                    ? [...value[name], r.id]
                    : value[name].filter((x) => x !== r.id),
                })
              }
            />
            {r.name}
          </label>
        ))}
        {rows && !rows.length ? (
          <p className="text-xs text-muted-foreground">{t("g3.delivery.noneYet")}</p>
        ) : null}
      </div>
    </fieldset>
  );
  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">{t("g3.delivery.assignHelp")}</p>
      <div className="grid gap-3 sm:grid-cols-3">
        {pick("jobs", t("g3.delivery.scopes.job"), jobs.data)}
        {pick("services", t("g3.delivery.scopes.service"), services.data)}
        {pick("subjects", t("g3.delivery.subjects"), subjects.data)}
      </div>
    </div>
  );
}
