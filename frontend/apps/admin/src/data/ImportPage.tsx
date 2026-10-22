import { unwrap } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  FigureStrip,
  PanelFooter,
  PanelRow,
  PanelRows,
  RuledPanel,
  RuledTable,
  SelectField,
  Spinner,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";

import { api } from "../api";
import { PanelLoading } from "../billing/moneyUi";
import { useIsPhone } from "../billing/useIsPhone";
import { ErrorList } from "../calendar/ErrorList";
import { RecordHeader } from "../components/RecordHeader";
import {
  BUSY,
  statsOf,
  useBatch,
  type ImportBatch,
  type ImportField,
  type ImportPreview,
} from "./api";
import { BatchStatus } from "./DataPage";

const DATE_ORDERS = ["DMY", "MDY", "YMD"] as const;
/** A quiet action after the primary; on phones it may wrap, so it sits on the content edge. */
const quietGhost = "text-muted-foreground max-sm:px-0";

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
  const phone = useIsPhone();
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
  const example = (header: string) =>
    preview.sample
      .map((row) => row[header])
      .filter(Boolean)
      .slice(0, 2)
      .join(", ");
  return (
    <form
      className="space-y-6"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <RuledPanel
        title={t("dataTransfer.mapping.columns")}
        description={t("dataTransfer.mapping.help")}
        flush
      >
        <RuledTable
          caption={t("dataTransfer.mapping.columns")}
          columns={[
            { key: "column", header: t("dataTransfer.mapping.column"), width: "min-w-36" },
            ...(phone ? [] : [{ key: "example", header: t("dataTransfer.mapping.example") }]),
            { key: "field", header: t("dataTransfer.mapping.field"), width: "w-1/3 min-w-44" },
          ]}
        >
          {preview.headers.map((header) => (
            <tr key={header}>
              <th scope="row" className="py-2.5 font-medium break-words">
                {header}
                {phone && example(header) ? (
                  <span className="block text-xs font-normal text-muted-foreground">
                    {example(header)}
                  </span>
                ) : null}
              </th>
              {phone ? null : (
                <td className="break-words text-muted-foreground">{example(header)}</td>
              )}
              <td className="py-1.5">
                <SelectField
                  size="sm"
                  hideLabel
                  label={t("dataTransfer.mapping.fieldFor", { column: header })}
                  value={columns[header] ?? ""}
                  onChange={(e) => setColumns({ ...columns, [header]: e.target.value })}
                  options={fieldOptions}
                />
              </td>
            </tr>
          ))}
        </RuledTable>
        {missing.length ? (
          <div className="border-t border-rule px-5 py-4">
            <Alert tone="warning">
              {t("dataTransfer.mapping.missing", {
                fields: missing.map((f) => f.label).join(", "),
              })}
            </Alert>
          </div>
        ) : null}
      </RuledPanel>
      {choiceColumns.length ? (
        <RuledPanel title={t("dataTransfer.mapping.values")} flush>
          <div className="divide-y divide-rule">
            {choiceColumns.map(([column, key]) => {
              const spec = fields.get(key);
              if (!spec) return null;
              return (
                <fieldset key={column} className="min-w-0 px-5 py-4">
                  <legend className="float-left mb-2 w-full text-sm font-medium">{column}</legend>
                  <div className="clear-left grid items-start gap-x-4 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
                    {(preview.distinct[column] ?? []).map((value) => (
                      <SelectField
                        key={value}
                        label={value}
                        value={values[key]?.[value] ?? ""}
                        onChange={(e) =>
                          setValues({
                            ...values,
                            [key]: { ...values[key], [value]: e.target.value },
                          })
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
          </div>
        </RuledPanel>
      ) : null}
      <RuledPanel title={t("designS9a.importOptions")} flush>
        <div className="grid items-start gap-x-4 gap-y-3 px-5 py-4 sm:grid-cols-2 lg:grid-cols-3">
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
        </div>
        {save.error ? (
          <div className="px-5 pb-4">
            <ErrorList error={save.error} />
          </div>
        ) : null}
        <PanelFooter>
          <Button type="submit" loading={save.isPending} disabled={missing.length > 0}>
            {t("dataTransfer.mapping.check")}
          </Button>
        </PanelFooter>
      </RuledPanel>
    </form>
  );
}

// --- step 2: dry run and preview grid ----------------------------------------------------------

function PreviewGrid({ batch }: { batch: ImportBatch }) {
  const { t } = useTranslation();
  const phone = useIsPhone();
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
  const rows = data?.results ?? [];
  const valuesOf = (raw: unknown) =>
    Object.entries(raw as Record<string, string>)
      .filter(([, v]) => v)
      .slice(0, 4)
      .map(([k, v]) => `${k}: ${v}`)
      .join(" · ");
  return (
    <RuledPanel
      title={t("dataTransfer.preview.title")}
      titleId="preview-heading"
      flush
      aside={
        <label className="inline-flex items-center gap-2">
          <input
            type="checkbox"
            checked={problems}
            onChange={(e) => setProblems(e.target.checked)}
          />
          {t("dataTransfer.preview.onlyProblems")}
        </label>
      }
    >
      <RuledTable
        caption={t("dataTransfer.preview.caption")}
        loading={!data}
        loadingLabel={t("grid.loading")}
        empty={data && rows.length === 0 ? t("dataTransfer.preview.none") : undefined}
        columns={[
          { key: "row", header: t("dataTransfer.preview.row"), end: true, width: "w-16" },
          { key: "status", header: t("dataTransfer.preview.status"), width: "min-w-32" },
          ...(phone ? [] : [{ key: "values", header: t("dataTransfer.preview.values") }]),
          { key: "problems", header: t("dataTransfer.preview.problems"), width: "min-w-40" },
        ]}
      >
        {rows.map((row) => (
          <tr key={row.id}>
            <th scope="row" className="py-2.5 text-right align-top font-normal tabular-nums">
              {row.row_number}
            </th>
            <td>
              <span
                className={
                  row.status === "invalid" || row.status === "failed"
                    ? "font-medium text-danger"
                    : undefined
                }
              >
                {t(`dataTransfer.rowStatus.${row.status}`)}
              </span>
              {row.action ? (
                <span className="block text-xs text-muted-foreground">
                  {t(`dataTransfer.actions.${row.action}`)}
                </span>
              ) : null}
              {phone ? (
                <span className="block text-xs break-words text-muted-foreground">
                  {valuesOf(row.raw)}
                </span>
              ) : null}
            </td>
            {phone ? null : (
              <td className="max-w-md truncate text-muted-foreground" title={valuesOf(row.raw)}>
                {valuesOf(row.raw)}
              </td>
            )}
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
      </RuledTable>
    </RuledPanel>
  );
}

function DryRun({ batch }: { batch: ImportBatch }) {
  const { t } = useTranslation();
  const stats = statsOf(batch);
  const will = Object.entries(stats.will ?? {}).flatMap(([target, verbs]) =>
    Object.entries(verbs).map(([verb, count]) => ({ target, verb, count })),
  );
  const sentence = t("dataTransfer.dryRun.rows", {
    valid: stats.valid ?? 0,
    invalid: stats.invalid ?? 0,
    warnings: stats.warnings ?? 0,
  });
  // With nothing to list, the sentence is the panel's body rather than a header line over an
  // empty panel.
  if (!will.length) {
    return (
      <RuledPanel title={t("dataTransfer.dryRun.title")} titleId="dry-run-heading">
        <p className="text-sm">{sentence}</p>
      </RuledPanel>
    );
  }
  return (
    <RuledPanel
      title={t("dataTransfer.dryRun.title")}
      titleId="dry-run-heading"
      description={sentence}
      flush
    >
      <PanelRows>
        {will.map(({ target, verb, count }) => (
          <PanelRow key={`${target}-${verb}`}>
            {t(`dataTransfer.dryRun.${verb}`, {
              count,
              what: t(`dataTransfer.targets.${target}`, { defaultValue: target }),
            })}
          </PanelRow>
        ))}
      </PanelRows>
    </RuledPanel>
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
  const back = <Link to="/data">{t("dataTransfer.title")}</Link>;
  if (error) {
    return (
      <div>
        <RecordHeader back={back} title={t("dataTransfer.title")} />
        <ErrorList error={error} />
      </div>
    );
  }
  if (!batch) return <Spinner label={t("common.loading")} />;
  const stats = statsOf(batch);
  const ready = batch.status === "validated" && !editing;
  const finished = ["completed", "finalised", "rolled_back"].includes(batch.status);
  const failed = stats.failed ?? 0;
  const invalid = stats.invalid ?? 0;
  return (
    <div>
      <RecordHeader
        back={back}
        title={t("dataTransfer.importOf", {
          what: t(`dataTransfer.entities.${batch.entity}`, { defaultValue: batch.entity }),
        })}
        description={
          <span className="inline-flex flex-wrap items-center gap-x-1.5">
            <span role="status" aria-live="polite" className="inline-flex items-center gap-1.5">
              <BatchStatus status={batch.status} />
              {BUSY.has(batch.status) ? <Spinner /> : null}
            </span>
            <span aria-hidden="true">·</span>
            <span className="break-all">{batch.filename}</span>
            <span aria-hidden="true">·</span>
            <span className="tabular-nums">{formatDateTime(batch.created_at, i18n.language)}</span>
          </span>
        }
        actions={
          ready ? (
            <>
              <Button size="sm" variant="secondary" onClick={() => setEditing(true)}>
                {t("dataTransfer.changeMapping")}
              </Button>
              <Button
                onClick={() => act.mutate("confirm")}
                disabled={!stats.valid}
                loading={act.isPending && act.variables === "confirm"}
              >
                {t("dataTransfer.confirm", { count: stats.valid ?? 0 })}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                className={quietGhost}
                onClick={() => act.mutate("cancel")}
              >
                {t("dataTransfer.cancel")}
              </Button>
            </>
          ) : finished && (batch.error_file || batch.can_rollback) ? (
            <>
              {batch.error_file ? (
                <Button size="sm" variant="secondary" onClick={() => report.mutate()}>
                  {t("dataTransfer.results.errorReport")}
                </Button>
              ) : null}
              {batch.can_rollback ? (
                <Button
                  size="sm"
                  variant="ghost"
                  className={quietGhost}
                  onClick={() => act.mutate("rollback")}
                >
                  {t("dataTransfer.results.rollback", {
                    date: batch.rollback_until
                      ? formatDateTime(batch.rollback_until, i18n.language)
                      : "",
                  })}
                </Button>
              ) : null}
            </>
          ) : null
        }
      />
      <div className="space-y-6">
        <ErrorList error={act.error ?? report.error} />
        {batch.error ? <Alert tone="danger">{batch.error}</Alert> : null}
        {mapping && !preview ? (
          <RuledPanel label={t("dataTransfer.mapping.columns")} flush>
            <PanelLoading label={t("grid.loading")} />
          </RuledPanel>
        ) : null}
        {mapping && preview ? (
          <MappingWizard batch={batch} preview={preview} onDone={() => setEditing(false)} />
        ) : null}
        {ready ? (
          <>
            <DryRun batch={batch} />
            <PreviewGrid batch={batch} />
          </>
        ) : null}
        {finished ? (
          <section className="space-y-6" aria-labelledby="results-heading">
            <h2 id="results-heading" className="sr-only">
              {t("dataTransfer.results.title")}
            </h2>
            <FigureStrip
              label={t("dataTransfer.results.title")}
              figures={(["created", "updated", "skipped", "failed", "invalid"] as const).map(
                (key) => ({
                  key,
                  label: t(`dataTransfer.results.${key}`),
                  value: stats[key] ?? 0,
                  tone:
                    (key === "failed" && failed > 0) || (key === "invalid" && invalid > 0)
                      ? "danger"
                      : "default",
                }),
              )}
            />
            {batch.status === "rolled_back" ? (
              <Alert tone="info">
                {t("dataTransfer.results.rolledBack", {
                  reverted: stats.reverted ?? 0,
                  kept: stats.kept ?? 0,
                })}
              </Alert>
            ) : null}
            <PreviewGrid batch={batch} />
          </section>
        ) : null}
      </div>
    </div>
  );
}
