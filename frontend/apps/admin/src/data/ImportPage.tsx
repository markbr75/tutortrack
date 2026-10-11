import { unwrap } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";

import { api } from "../api";
import { ErrorList } from "../calendar/ErrorList";
import {
  BUSY,
  statsOf,
  useBatch,
  type ImportBatch,
  type ImportField,
  type ImportPreview,
} from "./api";

const DATE_ORDERS = ["DMY", "MDY", "YMD"] as const;

function usePreview(id: string, enabled: boolean) {
  return useQuery({
    queryKey: ["imports", id, "preview"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/imports/{id}/preview", { params: { path: { id } } })),
    enabled,
  });
}

// --- step 1: columns and values -----------------------------------------------------------------

function MappingWizard({
  batch,
  preview,
  onDone,
}: {
  batch: ImportBatch;
  preview: ImportPreview;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [columns, setColumns] = useState<Record<string, string>>(preview.column_map);
  const [values, setValues] = useState<Record<string, Record<string, string>>>(
    preview.value_map as Record<string, Record<string, string>>,
  );
  const options = preview.options as Record<string, string>;
  const [upsert, setUpsert] = useState(options.upsert_key ?? "");
  const [dateOrder, setDateOrder] = useState(options.date_format ?? "");
  const [cutover, setCutover] = useState(options.cutover_date ?? "");
  const fields = new Map<string, ImportField>(preview.field_specs.map((f) => [f.key, f]));
  const used = new Set(Object.values(columns).filter(Boolean));
  const missing = preview.field_specs.filter((f) => f.required && !used.has(f.key));
  const fieldOptions = [
    { value: "", label: t("dataTransfer.mapping.ignore") },
    ...preview.field_specs.map((f) => ({
      value: f.key,
      label: f.required ? `${f.label} *` : f.label,
    })),
  ];
  const save = useMutation({
    mutationFn: async () => {
      const id = batch.id;
      await api
        .PUT("/api/v1/imports/{id}/mapping", {
          params: { path: { id } },
          body: {
            column_map: columns,
            value_map: values,
            options: {
              ...(upsert ? { upsert_key: upsert } : {}),
              ...(dateOrder ? { date_format: dateOrder } : {}),
              ...(cutover ? { cutover_date: cutover } : {}),
            },
          },
        })
        .then(unwrap);
      if (batch.status === "mapping") {
        unwrap(await api.POST("/api/v1/imports/{id}/submit", { params: { path: { id } } }));
      }
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["imports", batch.id] });
      onDone();
    },
  });
  const choiceColumns = Object.entries(columns).filter(([column, key]) => {
    const spec = fields.get(key);
    return spec && spec.choices.length > 0 && (preview.distinct[column] ?? []).length > 0;
  });
  return (
    <form
      className="space-y-6"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <section className="space-y-2">
        <h2 className="text-lg font-semibold">{t("dataTransfer.mapping.columns")}</h2>
        <p className="text-sm text-muted-foreground">{t("dataTransfer.mapping.help")}</p>
        <table className="w-full text-sm">
          <caption className="sr-only">{t("dataTransfer.mapping.columns")}</caption>
          <thead>
            <tr className="text-left">
              <th scope="col">{t("dataTransfer.mapping.column")}</th>
              <th scope="col">{t("dataTransfer.mapping.example")}</th>
              <th scope="col">{t("dataTransfer.mapping.field")}</th>
            </tr>
          </thead>
          <tbody>
            {preview.headers.map((header) => (
              <tr key={header} className="border-t border-border align-top">
                <th scope="row" className="py-1 font-medium">
                  {header}
                </th>
                <td className="py-1 text-muted-foreground">
                  {preview.sample
                    .map((row) => row[header])
                    .filter(Boolean)
                    .slice(0, 2)
                    .join(", ")}
                </td>
                <td className="py-1">
                  <SelectField
                    label={t("dataTransfer.mapping.fieldFor", { column: header })}
                    value={columns[header] ?? ""}
                    onChange={(e) => setColumns({ ...columns, [header]: e.target.value })}
                    options={fieldOptions}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {missing.length ? (
          <Alert tone="warning">
            {t("dataTransfer.mapping.missing", { fields: missing.map((f) => f.label).join(", ") })}
          </Alert>
        ) : null}
      </section>
      {choiceColumns.length ? (
        <section className="space-y-3">
          <h2 className="text-lg font-semibold">{t("dataTransfer.mapping.values")}</h2>
          {choiceColumns.map(([column, key]) => {
            const spec = fields.get(key);
            if (!spec) return null;
            return (
              <fieldset key={column} className="space-y-2">
                <legend className="font-medium">{column}</legend>
                <div className="grid gap-2 sm:grid-cols-2">
                  {(preview.distinct[column] ?? []).map((value) => (
                    <SelectField
                      key={value}
                      label={value}
                      value={values[key]?.[value] ?? ""}
                      onChange={(e) =>
                        setValues({ ...values, [key]: { ...values[key], [value]: e.target.value } })
                      }
                      options={[
                        { value: "", label: t("dataTransfer.mapping.asIs") },
                        ...spec.choices.map((c) => ({
                          value: c,
                          label: t(`dataTransfer.choices.${c}`, { defaultValue: c }),
                        })),
                      ]}
                    />
                  ))}
                </div>
              </fieldset>
            );
          })}
        </section>
      ) : null}
      <section className="grid gap-3 sm:grid-cols-3">
        {preview.upsert_keys.length > 1 ? (
          <SelectField
            label={t("dataTransfer.mapping.upsert")}
            value={upsert}
            onChange={(e) => setUpsert(e.target.value)}
            options={[
              { value: "", label: t("dataTransfer.mapping.upsertDefault") },
              ...preview.upsert_keys.map((k) => ({
                value: k,
                label: t(`dataTransfer.upsert.${k}`),
              })),
            ]}
          />
        ) : null}
        <SelectField
          label={t("dataTransfer.mapping.dateOrder")}
          value={dateOrder}
          onChange={(e) => setDateOrder(e.target.value)}
          options={[
            { value: "", label: t("dataTransfer.mapping.dateDefault") },
            ...DATE_ORDERS.map((d) => ({ value: d, label: t(`dataTransfer.dates.${d}`) })),
          ]}
        />
        <TextField
          label={t("dataTransfer.mapping.cutover")}
          type="date"
          value={cutover}
          onChange={(e) => setCutover(e.target.value)}
          hint={t("dataTransfer.mapping.cutoverHint")}
        />
      </section>
      <Button type="submit" disabled={save.isPending || missing.length > 0}>
        {t("dataTransfer.mapping.check")}
      </Button>
      <ErrorList error={save.error} />
    </form>
  );
}

// --- step 2: dry run and preview grid ----------------------------------------------------------

function PreviewGrid({ batch }: { batch: ImportBatch }) {
  const { t } = useTranslation();
  const [problems, setProblems] = useState(true);
  const { data } = useQuery({
    queryKey: ["imports", batch.id, "rows", problems, batch.status],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/imports/{id}/rows", {
          params: { path: { id: batch.id }, query: { problems } },
        }),
      ),
  });
  return (
    <section className="space-y-2" aria-labelledby="preview-heading">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="preview-heading" className="text-lg font-semibold">
          {t("dataTransfer.preview.title")}
        </h2>
        <label className="inline-flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={problems}
            onChange={(e) => setProblems(e.target.checked)}
          />
          {t("dataTransfer.preview.onlyProblems")}
        </label>
      </div>
      {!data ? (
        <Spinner />
      ) : data.results.length === 0 ? (
        <p className="text-muted-foreground">{t("dataTransfer.preview.none")}</p>
      ) : (
        <div className="overflow-x-auto" tabIndex={0} aria-label={t("dataTransfer.preview.title")}>
          <table className="w-full text-sm">
            <caption className="sr-only">{t("dataTransfer.preview.caption")}</caption>
            <thead>
              <tr className="text-left">
                <th scope="col">{t("dataTransfer.preview.row")}</th>
                <th scope="col">{t("dataTransfer.preview.status")}</th>
                <th scope="col">{t("dataTransfer.preview.values")}</th>
                <th scope="col">{t("dataTransfer.preview.problems")}</th>
              </tr>
            </thead>
            <tbody>
              {data.results.map((row) => (
                <tr key={row.id} className="border-t border-border align-top">
                  <th scope="row" className="font-normal">
                    {row.row_number}
                  </th>
                  <td>
                    {t(`dataTransfer.rowStatus.${row.status}`)}
                    {row.action ? ` · ${t(`dataTransfer.actions.${row.action}`)}` : ""}
                  </td>
                  <td className="max-w-md truncate">
                    {Object.entries(row.raw as Record<string, string>)
                      .filter(([, v]) => v)
                      .slice(0, 4)
                      .map(([k, v]) => `${k}: ${v}`)
                      .join(" · ")}
                  </td>
                  <td>
                    <ul>
                      {row.row_errors.map((e, i) => (
                        <li key={`e${i}`} className="text-danger">
                          {e.message}
                        </li>
                      ))}
                      {row.row_warnings.map((w, i) => (
                        <li key={`w${i}`} className="text-muted-foreground">
                          {w.message}
                        </li>
                      ))}
                    </ul>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function DryRun({ batch }: { batch: ImportBatch }) {
  const { t } = useTranslation();
  const stats = statsOf(batch);
  const will = Object.entries(stats.will ?? {});
  return (
    <section className="space-y-2" aria-labelledby="dry-run-heading">
      <h2 id="dry-run-heading" className="text-lg font-semibold">
        {t("dataTransfer.dryRun.title")}
      </h2>
      <p>
        {t("dataTransfer.dryRun.rows", {
          valid: stats.valid ?? 0,
          invalid: stats.invalid ?? 0,
          warnings: stats.warnings ?? 0,
        })}
      </p>
      {will.length ? (
        <ul className="list-disc pl-5">
          {will.map(([target, verbs]) =>
            Object.entries(verbs).map(([verb, count]) => (
              <li key={`${target}-${verb}`}>
                {t(`dataTransfer.dryRun.${verb}`, {
                  count,
                  what: t(`dataTransfer.targets.${target}`, { defaultValue: target }),
                })}
              </li>
            )),
          )}
        </ul>
      ) : null}
    </section>
  );
}

// --- the page ---------------------------------------------------------------------------------

export function ImportPage({ batchId }: { batchId: string }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const { data: batch, error } = useBatch(batchId);
  const [editing, setEditing] = useState(false);
  const mapping = batch?.status === "mapping" || editing;
  const { data: preview } = usePreview(batchId, Boolean(batch) && mapping);
  const path = { params: { path: { id: batchId } } };
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["imports", batchId] });
  const act = useMutation({
    mutationFn: async (kind: "confirm" | "cancel" | "rollback") => {
      if (kind === "confirm") return unwrap(await api.POST("/api/v1/imports/{id}/confirm", path));
      if (kind === "cancel") return unwrap(await api.POST("/api/v1/imports/{id}/cancel", path));
      return unwrap(await api.POST("/api/v1/imports/{id}/rollback", path));
    },
    onSuccess: refresh,
  });
  const report = useMutation({
    mutationFn: async () => unwrap(await api.GET("/api/v1/imports/{id}/error-report", path)),
    onSuccess: (link) => window.location.assign(link.url),
  });
  useEffect(() => {
    if (batch && batch.status !== "validated") setEditing(false);
  }, [batch]);
  if (error) return <ErrorList error={error} />;
  if (!batch) return <Spinner />;
  const stats = statsOf(batch);
  return (
    <div className="space-y-6">
      <nav aria-label={t("dataTransfer.title")}>
        <Link to="/data" className="text-sm underline">
          {t("dataTransfer.back")}
        </Link>
      </nav>
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold">
          {t("dataTransfer.importOf", {
            what: t(`dataTransfer.entities.${batch.entity}`, { defaultValue: batch.entity }),
          })}
        </h1>
        <p className="text-muted-foreground">
          {batch.filename} · {formatDateTime(batch.created_at, i18n.language)}
        </p>
        <p role="status" aria-live="polite" className="font-medium">
          {t(`dataTransfer.status.${batch.status}`)}
          {BUSY.has(batch.status) ? <Spinner /> : null}
        </p>
      </header>
      {batch.error ? <Alert tone="danger">{batch.error}</Alert> : null}
      {mapping && preview ? (
        <MappingWizard batch={batch} preview={preview} onDone={() => setEditing(false)} />
      ) : null}
      {batch.status === "validated" && !editing ? (
        <>
          <DryRun batch={batch} />
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => act.mutate("confirm")} disabled={!stats.valid || act.isPending}>
              {t("dataTransfer.confirm", { count: stats.valid ?? 0 })}
            </Button>
            <Button variant="secondary" onClick={() => setEditing(true)}>
              {t("dataTransfer.changeMapping")}
            </Button>
            <Button variant="ghost" onClick={() => act.mutate("cancel")}>
              {t("dataTransfer.cancel")}
            </Button>
          </div>
          <PreviewGrid batch={batch} />
        </>
      ) : null}
      {["completed", "finalised", "rolled_back"].includes(batch.status) ? (
        <section className="space-y-3" aria-labelledby="results-heading">
          <h2 id="results-heading" className="text-lg font-semibold">
            {t("dataTransfer.results.title")}
          </h2>
          <dl className="grid grid-cols-2 gap-2 sm:grid-cols-5">
            {(["created", "updated", "skipped", "failed", "invalid"] as const).map((key) => (
              <div key={key} className="rounded-md border border-border p-2">
                <dt className="text-sm text-muted-foreground">
                  {t(`dataTransfer.results.${key}`)}
                </dt>
                <dd className="text-xl font-semibold">{stats[key] ?? 0}</dd>
              </div>
            ))}
          </dl>
          {batch.status === "rolled_back" ? (
            <Alert tone="info">
              {t("dataTransfer.results.rolledBack", {
                reverted: stats.reverted ?? 0,
                kept: stats.kept ?? 0,
              })}
            </Alert>
          ) : null}
          <div className="flex flex-wrap gap-2">
            {batch.error_file ? (
              <Button variant="secondary" onClick={() => report.mutate()}>
                {t("dataTransfer.results.errorReport")}
              </Button>
            ) : null}
            {batch.can_rollback ? (
              <Button variant="ghost" onClick={() => act.mutate("rollback")}>
                {t("dataTransfer.results.rollback", {
                  date: batch.rollback_until
                    ? formatDateTime(batch.rollback_until, i18n.language)
                    : "",
                })}
              </Button>
            ) : null}
          </div>
          <PreviewGrid batch={batch} />
        </section>
      ) : null}
      <ErrorList error={act.error ?? report.error} />
    </div>
  );
}
