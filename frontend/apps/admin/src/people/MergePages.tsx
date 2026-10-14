import { ApiError, unwrap, type components } from "@tutortrack/api-client";
import { formatDate, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, ErrorFallback, Spinner, Tabs, TextField } from "@tutortrack/ui";
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
      <h1 className="mb-2 text-2xl font-semibold">{t("peopleTools.duplicates.title")}</h1>
      <p className="mb-4 text-sm text-muted-foreground">{t("peopleTools.duplicates.intro")}</p>
      <Tabs
        label={t("peopleTools.duplicates.tabs")}
        tabs={(["client", "contact", "student"] as const).map((key) => ({
          key,
          label: t(`peopleTools.duplicates.${key}`),
        }))}
        value={kind}
        onChange={setKind}
      >
        {pairs.isPending ? <Spinner label={t("grid.loading")} /> : null}
        {pairs.isError ? (
          <ErrorFallback
            title={t("errors.generic")}
            retryLabel={t("errors.retry")}
            onRetry={() => void pairs.refetch()}
          />
        ) : null}
        {pairs.data && pairs.data.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("peopleTools.duplicates.none")}</p>
        ) : null}
        {pairs.data && pairs.data.length > 0 ? (
          <div className="overflow-x-auto rounded-md border border-border">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">{t("peopleTools.duplicates.title")}</caption>
              <thead className="bg-muted text-muted-foreground">
                <tr>
                  <th scope="col" className="px-3 py-2 font-medium">
                    {t("peopleTools.duplicates.older")}
                  </th>
                  <th scope="col" className="px-3 py-2 font-medium">
                    {t("peopleTools.duplicates.newer")}
                  </th>
                  <th scope="col" className="px-3 py-2 font-medium">
                    {t("peopleTools.duplicates.reasonLabel")}
                  </th>
                  <th scope="col" className="px-3 py-2 font-medium">
                    <span className="sr-only">{t("peopleTools.duplicates.review")}</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {pairs.data.map((pair: Pair) => (
                  <tr key={`${pair.a.id}-${pair.b.id}`} className="border-t border-border">
                    {[pair.a, pair.b].map((person) => (
                      <td key={person.id} className="px-3 py-2 align-top">
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
                    <td className="px-3 py-2 align-top">
                      {t(`peopleTools.duplicates.reason.${pair.reason}`, {
                        defaultValue: pair.reason,
                      })}
                    </td>
                    <td className="px-3 py-2 align-top">
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
    <section className="mt-4 rounded-md border border-border p-4">
      <h2 className="mb-2 font-semibold">{t("peopleTools.merge.chooseTarget")}</h2>
      <form role="search" onSubmit={submit} className="flex flex-wrap items-end gap-2">
        <TextField
          label={t("peopleTools.merge.search")}
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <Button type="submit">{t("peopleTools.merge.searchButton")}</Button>
      </form>
      {found.isFetching ? <Spinner label={t("grid.loading")} /> : null}
      {search && found.data && results.length === 0 ? (
        <p className="mt-2 text-sm text-muted-foreground">{t("peopleTools.merge.noMatches")}</p>
      ) : null}
      <ul className="mt-3 space-y-2">
        {results.map((c) => (
          <li key={c.id} className="flex flex-wrap items-center gap-2">
            <span>{[c.name, c.detail].filter(Boolean).join(" · ")}</span>
            <Button size="sm" variant="secondary" onClick={() => onPick(c.id)}>
              {t("peopleTools.merge.pick", { name: c.name })}
            </Button>
          </li>
        ))}
      </ul>
    </section>
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
      <section>
        <h1 className="mb-4 text-2xl font-semibold">{t(`peopleTools.merge.entity.${entity}`)}</h1>
        <Alert tone="success">{t("peopleTools.merge.merged", { name: kept.name })}</Alert>
        {merge.data.notes.length ? (
          <div className="mt-3">
            <h2 className="font-semibold">{t("peopleTools.merge.notes")}</h2>
            <ul className="list-disc pl-5 text-sm">
              {merge.data.notes.map((note) => (
                <li key={note}>{note}</li>
              ))}
            </ul>
          </div>
        ) : null}
        {entity !== "contacts" ? (
          <p className="mt-4">
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
      <h1 className="mb-2 text-2xl font-semibold">{t(`peopleTools.merge.entity.${entity}`)}</h1>
      <p className="mb-4 max-w-prose text-sm text-muted-foreground">
        {t("peopleTools.merge.intro")}
      </p>
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
            <Alert tone="warning" title={t("peopleTools.merge.warnings")} className="mt-3">
              <ul className="list-disc pl-5">
                {data.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </Alert>
          ) : null}
          <div className="mt-4 overflow-x-auto rounded-md border border-border">
            <table className="w-full text-left text-sm">
              <caption className="px-3 py-2 text-left font-semibold">
                {t("peopleTools.merge.values")}
              </caption>
              <thead className="bg-muted text-muted-foreground">
                <tr>
                  <th scope="col" className="px-3 py-2 font-medium">
                    {t("peopleTools.merge.field")}
                  </th>
                  <th scope="col" className="px-3 py-2 font-medium">
                    {t("peopleTools.merge.duplicate")}: {data.source.name}
                  </th>
                  <th scope="col" className="px-3 py-2 font-medium">
                    {t("peopleTools.merge.keep")}: {data.target.name}
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.values.map((row) => {
                  const chosen = choiceOf(row.name, row.default);
                  const group = `merge-${row.name}`;
                  return (
                    <tr key={row.name} className="border-t border-border">
                      <th scope="row" className="px-3 py-2 align-top font-medium">
                        {row.label}
                      </th>
                      {row.same || row.hidden ? (
                        <td colSpan={2} className="px-3 py-2 text-muted-foreground">
                          {row.hidden
                            ? t("peopleTools.merge.hidden")
                            : `${display(row.target, false, t)} · ${t("peopleTools.merge.same")}`}
                        </td>
                      ) : (
                        (["source", "target"] as const).map((side) => (
                          <td key={side} className="px-3 py-2 align-top">
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
          <section className="mt-4">
            <h2 className="font-semibold">{t("peopleTools.merge.moves")}</h2>
            {data.moves.length ? (
              <ul className="mt-1 list-disc pl-5 text-sm">
                {data.moves.map((m) => (
                  <li key={m.key}>
                    {m.label}: {m.count}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">{t("peopleTools.merge.nothingMoves")}</p>
            )}
          </section>
          <div className="mt-4 flex flex-wrap items-center gap-3">
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
            <Alert tone="danger" className="mt-3">
              {merge.error instanceof ApiError ? merge.error.message : t("errors.generic")}
            </Alert>
          ) : null}
          <div className="mt-4 flex flex-wrap gap-2">
            <Button
              type="submit"
              variant="danger"
              disabled={!confirmed || !data.can_merge}
              loading={merge.isPending}
            >
              {merge.isPending ? t("peopleTools.merge.merging") : t("peopleTools.merge.submit")}
            </Button>
            <Button type="button" variant="secondary" onClick={swap}>
              {t("peopleTools.merge.swap")}
            </Button>
          </div>
        </form>
      ) : null}
    </section>
  );
}
