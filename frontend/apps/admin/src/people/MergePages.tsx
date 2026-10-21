import { ApiError, unwrap, type components } from "@tutortrack/api-client";
import { formatDate, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  ErrorFallback,
  PageHeader,
  Panel,
  PanelRow,
  PanelRows,
  Spinner,
  Tabs,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { useState, type FormEvent } from "react";

import { api } from "../api";
import { actionLink } from "./listHelpers";

/** FR-05-13 merge tool (gap batch G1): the duplicates list and the merge screen. */

export type MergeEntity = "clients" | "contacts" | "students";
type Pair = components["schemas"]["DuplicatePair"];
type Preview = components["schemas"]["MergePreview"];
type PairType = "client" | "contact" | "student";

const ENTITY_OF: Record<PairType, MergeEntity> = {
  client: "clients",
  contact: "contacts",
  student: "students",
};
const linkClass = "font-medium underline-offset-2 hover:underline";

function recordLink(entity: MergeEntity, id: string, clientId?: string) {
  if (entity === "students") return { to: "/students/$studentId", params: { studentId: id } };
  return { to: "/clients/$clientId", params: { clientId: clientId ?? id } };
}

/** `/people/duplicates`: pairs that look like the same family or person. */
export function DuplicatesPage() {
  const { t, i18n } = useTranslation();
  const [kind, setKind] = useState<PairType>("client");
  const pairs = useQuery({
    queryKey: ["duplicate-pairs", kind],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/people/duplicates/pairs", { params: { query: { type: kind } } }),
      ),
  });
  const entity = ENTITY_OF[kind];
  return (
    <section>
      <PageHeader
        title={t("peopleTools.duplicates.title")}
        description={t("peopleTools.duplicates.intro")}
      />
      <Tabs
        label={t("peopleTools.duplicates.tabs")}
        tabs={(["client", "contact", "student"] as const).map((key) => ({
          key,
          label: t(`peopleTools.duplicates.${key}`),
        }))}
        value={kind}
        onChange={setKind}
      >
        {pairs.isPending ? (
          <div className="rounded-xl border border-border bg-surface">
            <Spinner className="sr-only" label={t("grid.loading")} />
            {[0, 1, 2].map((i) => (
              <div key={i} className="border-t border-rule px-4 py-3 first:border-0">
                <div aria-hidden="true" className="h-4 animate-pulse rounded bg-muted" />
              </div>
            ))}
          </div>
        ) : null}
        {pairs.isError ? (
          <ErrorFallback
            title={t("errors.generic")}
            retryLabel={t("errors.retry")}
            onRetry={() => void pairs.refetch()}
          />
        ) : null}
        {pairs.data && pairs.data.length === 0 ? (
          <p className="rounded-xl border border-border bg-surface px-4 py-10 text-center text-sm text-muted-foreground">
            {t("peopleTools.duplicates.none")}
          </p>
        ) : null}
        {pairs.data && pairs.data.length > 0 ? (
          <div
            role="region"
            aria-label={t("peopleTools.duplicates.title")}
            tabIndex={0}
            className="relative overflow-x-auto rounded-xl border border-border bg-surface"
          >
            <table className="w-full text-left text-sm">
              <caption className="sr-only">{t("peopleTools.duplicates.title")}</caption>
              <thead className="border-b border-border">
                <tr>
                  <th scope="col" className="px-4 py-2.5 whitespace-nowrap">
                    {t("peopleTools.duplicates.older")}
                  </th>
                  <th scope="col" className="px-4 py-2.5 whitespace-nowrap">
                    {t("peopleTools.duplicates.newer")}
                  </th>
                  <th scope="col" className="px-4 py-2.5 whitespace-nowrap">
                    {t("peopleTools.duplicates.reasonLabel")}
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    <span className="sr-only">{t("peopleTools.duplicates.review")}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {pairs.data.map((pair: Pair) => (
                  <tr key={`${pair.a.id}-${pair.b.id}`}>
                    {[pair.a, pair.b].map((person) => (
                      <td key={person.id} className="px-4 py-2.5 align-top">
                        <Link
                          className={linkClass}
                          {...recordLink(entity, person.id, person.client_id)}
                        >
                          {person.name}
                        </Link>
                        <p className="text-xs text-muted-foreground">
                          {[person.detail, formatDate(person.created_at, i18n.language)]
                            .filter(Boolean)
                            .join(" · ")}
                        </p>
                      </td>
                    ))}
                    <td className="px-4 py-2.5 align-top">
                      {t(`peopleTools.duplicates.reason.${pair.reason}`, {
                        defaultValue: pair.reason,
                      })}
                    </td>
                    <td className="px-4 py-2.5 text-right align-top">
                      <Link
                        className={actionLink}
                        to="/people/merge/$entity/$sourceId/$targetId"
                        params={{ entity, sourceId: pair.b.id, targetId: pair.a.id }}
                        aria-label={t("peopleTools.duplicates.reviewPair", {
                          a: pair.a.name,
                          b: pair.b.name,
                        })}
                      >
                        {t("peopleTools.duplicates.review")}
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </Tabs>
    </section>
  );
}

interface Candidate {
  id: string;
  name: string;
  detail: string;
}

/** Find the record to keep (same kind; for contacts and students, the same family). */
function TargetPicker({
  entity,
  sourceId,
  onPick,
}: {
  entity: MergeEntity;
  sourceId: string;
  onPick: (id: string) => void;
}) {
  const { t } = useTranslation();
  const [q, setQ] = useState("");
  const [search, setSearch] = useState("");
  const found = useQuery({
    queryKey: ["merge-candidates", entity, search],
    enabled: search.length > 1,
    queryFn: async (): Promise<Candidate[]> => {
      if (entity === "clients") {
        const page = unwrap(await api.GET("/api/v1/clients", { params: { query: { q: search } } }));
        return page.results.map((c) => ({ id: c.id, name: c.display_name, detail: "" }));
      }
      if (entity === "students") {
        const page = unwrap(
          await api.GET("/api/v1/students", { params: { query: { q: search } } }),
        );
        return page.results.map((s) => ({
          id: s.id,
          name: s.full_name ?? "",
          detail: s.year_group ?? "",
        }));
      }
      const page = unwrap(await api.GET("/api/v1/contacts", { params: { query: { q: search } } }));
      return page.results.map((c) => ({
        id: c.id,
        name: c.full_name ?? "",
        detail: c.email ?? "",
      }));
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setSearch(q.trim());
  };
  const results = (found.data ?? []).filter((c) => c.id !== sourceId);
  return (
    <Panel title={t("peopleTools.merge.chooseTarget")} flush className="max-w-3xl">
      <form role="search" onSubmit={submit} className="flex flex-wrap items-end gap-2 px-5 py-4">
        <div className="min-w-56 flex-1">
          <TextField
            label={t("peopleTools.merge.search")}
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
        <Button type="submit" variant="secondary">
          {t("peopleTools.merge.searchButton")}
        </Button>
      </form>
      {found.isFetching ? (
        <div className="border-t border-rule px-5 py-3">
          <Spinner label={t("grid.loading")} />
        </div>
      ) : null}
      {search && found.data && results.length === 0 ? (
        <p className="border-t border-rule px-5 py-4 text-sm text-muted-foreground">
          {t("peopleTools.merge.noMatches")}
        </p>
      ) : null}
      {results.length ? (
        <PanelRows className="border-t border-rule">
          {results.map((c) => (
            <PanelRow key={c.id} className="flex flex-wrap items-center justify-between gap-2">
              <span className="min-w-0">
                <span className="block font-medium">{c.name}</span>
                {c.detail ? (
                  <span className="block text-xs text-muted-foreground">{c.detail}</span>
                ) : null}
              </span>
              <Button size="sm" variant="secondary" onClick={() => onPick(c.id)}>
                {t("peopleTools.merge.pick", { name: c.name })}
              </Button>
            </PanelRow>
          ))}
        </PanelRows>
      ) : null}
    </Panel>
  );
}

function display(value: string, hidden: boolean, t: (key: string) => string): string {
  if (hidden) return t("peopleTools.merge.hidden");
  if (value === "yes") return t("peopleTools.merge.yes");
  if (value === "no") return t("peopleTools.merge.no");
  return value || t("peopleTools.merge.empty");
}

/** The merge screen: values side by side, what moves, problems, and an explicit
 * confirmation (merging can't be undone). */
export function MergePage({
  entity,
  sourceId,
  targetId,
}: {
  entity: MergeEntity;
  sourceId: string;
  targetId?: string;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [choices, setChoices] = useState<Record<string, "source" | "target">>({});
  const [confirmed, setConfirmed] = useState(false);
  const preview = useQuery({
    queryKey: ["merge-preview", entity, sourceId, targetId],
    enabled: Boolean(targetId),
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/merge/{entity}/preview", {
          params: {
            path: { entity },
            query: { source: sourceId, target: targetId ?? "" },
          },
        }),
      ),
  });
  const merge = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/merge/{entity}", {
          params: { path: { entity } },
          body: { source: sourceId, target: targetId ?? "", choices, confirm: confirmed },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries();
    },
  });
  const pick = (id: string) =>
    void navigate({
      to: "/people/merge/$entity/$sourceId/$targetId",
      params: { entity, sourceId, targetId: id },
    });
  const swap = () => {
    if (!targetId) return;
    setChoices({});
    void navigate({
      to: "/people/merge/$entity/$sourceId/$targetId",
      params: { entity, sourceId: targetId, targetId: sourceId },
    });
  };
  const data: Preview | undefined = preview.data;
  const choiceOf = (name: string, fallback: "source" | "target") => choices[name] ?? fallback;
  if (merge.data && data) {
    const kept = data.target;
    return (
      <section className="max-w-3xl space-y-6">
        <PageHeader title={t(`peopleTools.merge.entity.${entity}`)} className="mb-0" />
        <Alert tone="success">{t("peopleTools.merge.merged", { name: kept.name })}</Alert>
        {merge.data.notes.length ? (
          <Panel title={t("peopleTools.merge.notes")} flush>
            <PanelRows>
              {merge.data.notes.map((note) => (
                <PanelRow key={note}>{note}</PanelRow>
              ))}
            </PanelRows>
          </Panel>
        ) : null}
        {entity !== "contacts" ? (
          <p>
            <Link className={actionLink} {...recordLink(entity, kept.id)}>
              {t("peopleTools.merge.open", { name: kept.name })}
            </Link>
          </p>
        ) : null}
      </section>
    );
  }
  return (
    <section>
      <PageHeader
        title={t(`peopleTools.merge.entity.${entity}`)}
        description={<span className="block max-w-prose">{t("peopleTools.merge.intro")}</span>}
      />
      {!targetId ? <TargetPicker entity={entity} sourceId={sourceId} onPick={pick} /> : null}
      {targetId && preview.isPending ? <Spinner label={t("grid.loading")} /> : null}
      {preview.isError ? (
        <ErrorFallback
          title={t("errors.generic")}
          retryLabel={t("errors.retry")}
          onRetry={() => void preview.refetch()}
        />
      ) : null}
      {data ? (
        <form
          className="max-w-4xl space-y-6"
          onSubmit={(e) => {
            e.preventDefault();
            if (confirmed && data.can_merge) merge.mutate();
          }}
        >
          {data.problems.length ? (
            <Alert tone="danger" title={t("peopleTools.merge.problems")}>
              <ul className="list-disc pl-5">
                {data.problems.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            </Alert>
          ) : null}
          {data.warnings.length ? (
            <Alert tone="warning" title={t("peopleTools.merge.warnings")}>
              <ul className="list-disc pl-5">
                {data.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </Alert>
          ) : null}
          <div
            role="region"
            aria-label={t("peopleTools.merge.values")}
            tabIndex={0}
            className="relative overflow-x-auto rounded-xl border border-border bg-surface"
          >
            <table className="w-full text-left text-sm">
              <caption className="border-b border-border px-5 py-3.5 text-left text-base font-semibold">
                {t("peopleTools.merge.values")}
              </caption>
              <thead className="border-b border-border">
                <tr>
                  <th scope="col" className="w-40 px-5 py-2.5">
                    {t("peopleTools.merge.field")}
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    {t("peopleTools.merge.duplicate")}: {data.source.name}
                  </th>
                  <th scope="col" className="px-4 py-2.5">
                    {t("peopleTools.merge.keep")}: {data.target.name}
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.values.map((row) => {
                  const chosen = choiceOf(row.name, row.default);
                  const group = `merge-${row.name}`;
                  return (
                    <tr key={row.name}>
                      <th scope="row" className="px-5 py-2.5 align-top font-medium">
                        {row.label}
                      </th>
                      {row.same || row.hidden ? (
                        <td colSpan={2} className="px-4 py-2.5 text-muted-foreground">
                          {row.hidden
                            ? t("peopleTools.merge.hidden")
                            : `${display(row.target, false, t)} · ${t("peopleTools.merge.same")}`}
                        </td>
                      ) : (
                        (["source", "target"] as const).map((side) => (
                          <td key={side} className="px-4 py-2.5 align-top">
                            <label className="flex items-start gap-2">
                              <input
                                type="radio"
                                name={group}
                                className="mt-1 size-4"
                                checked={chosen === side}
                                onChange={() => setChoices((c) => ({ ...c, [row.name]: side }))}
                                aria-label={t(
                                  side === "source"
                                    ? "peopleTools.merge.useDuplicate"
                                    : "peopleTools.merge.useKept",
                                  { field: row.label },
                                )}
                              />
                              <span className="break-words">{display(row[side], false, t)}</span>
                            </label>
                          </td>
                        ))
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <Panel title={t("peopleTools.merge.moves")} flush>
            {data.moves.length ? (
              <PanelRows>
                {data.moves.map((m) => (
                  <PanelRow key={m.key} className="tabular-nums">
                    {m.label}: {m.count}
                  </PanelRow>
                ))}
              </PanelRows>
            ) : (
              <p className="px-5 py-4 text-sm text-muted-foreground">
                {t("peopleTools.merge.nothingMoves")}
              </p>
            )}
          </Panel>
          <div className="flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="size-4"
                checked={confirmed}
                disabled={!data.can_merge}
                onChange={(e) => setConfirmed(e.target.checked)}
              />
              {t("peopleTools.merge.confirm")}
            </label>
          </div>
          {merge.error ? (
            <Alert tone="danger">
              {merge.error instanceof ApiError ? merge.error.message : t("errors.generic")}
            </Alert>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="secondary" onClick={swap}>
              {t("peopleTools.merge.swap")}
            </Button>
            <Button
              type="submit"
              variant="danger"
              disabled={!confirmed || !data.can_merge}
              loading={merge.isPending}
            >
              {merge.isPending ? t("peopleTools.merge.merging") : t("peopleTools.merge.submit")}
            </Button>
          </div>
        </form>
      ) : null}
    </section>
  );
}
