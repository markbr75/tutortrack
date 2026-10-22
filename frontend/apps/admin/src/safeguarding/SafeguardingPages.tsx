import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  CheckboxField,
  Disclosure,
  FactList,
  PageHeader,
  PanelFooter,
  PanelRow,
  PanelRows,
  RuledPanel,
  SelectField,
  Spinner,
  Tabs,
  TextAreaField,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { api, usePermission } from "../api";
import { RecordHeader } from "../components/RecordHeader";
import { AreaSettings, Cell, FormCard, Table, TextArea } from "../privacy/shared";
import { PAGE } from "../privacy/util";

type Concern = components["schemas"]["Concern"];

const CATEGORIES = [
  "physical", "emotional", "sexual", "neglect", "online", "self_harm", "bullying",
  "radicalisation", "allegation", "conduct", "other",
] as const; // prettier-ignore
const ACTIONS = [
  "note", "contacted_family", "referred_social_care", "referred_lado", "referred_police",
] as const; // prettier-ignore
const STATUSES = ["open", "in_review", "referred", "closed"] as const;

const link = "font-medium text-link underline-offset-2 hover:underline";
const quiet = "text-muted-foreground";

type Tab = "concerns" | "flags" | "loneWorking" | "settings";

/** Safeguarding (E29-T08/T09), for Designated Safeguarding Leads: cases, flagged messages,
 * lone-working visits and the safeguarding settings. */
export function SafeguardingPage() {
  const { t } = useTranslation();
  const isDsl = usePermission("safeguarding.dsl");
  const monitors = usePermission("safeguarding.lone_working.monitor");
  const settings = usePermission("org.settings.view");
  const tabs: Tab[] = [
    ...(isDsl ? (["concerns", "flags"] as Tab[]) : []),
    ...(monitors ? (["loneWorking"] as Tab[]) : []),
    ...(settings ? (["settings"] as Tab[]) : []),
  ];
  const [tab, setTab] = useState<Tab>(tabs[0] ?? "concerns");
  if (!tabs.length) return <Alert tone="danger">{t("safeguarding.forbidden")}</Alert>;
  return (
    <section className="max-w-5xl">
      <PageHeader title={t("safeguarding.title")} description={t("safeguarding.confidential")} />
      <Tabs
        label={t("safeguarding.title")}
        tabs={tabs.map((key) => ({ key, label: t(`safeguarding.tabs.${key}`) }))}
        value={tab}
        onChange={setTab}
      >
        {tab === "concerns" ? <ConcernsSection /> : null}
        {tab === "flags" ? <FlagsSection /> : null}
        {tab === "loneWorking" ? <LoneWorkingSection /> : null}
        {tab === "settings" ? (
          <AreaSettings area="safeguarding" label={t("safeguarding.tabs.settings")} />
        ) : null}
      </Tabs>
    </section>
  );
}

function ConcernsSection() {
  const { t, i18n } = useTranslation();
  const [status, setStatus] = useState("");
  const concerns = useQuery({
    queryKey: ["safeguarding", "concerns", status],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/safeguarding/concerns", {
          params: { query: { ...PAGE, ...(status ? { status: status as "open" } : {}) } },
        }),
      ),
  });
  const rows = concerns.data?.results ?? [];
  return (
    <Table
      caption={t("safeguarding.cases")}
      loading={concerns.isPending}
      empty={concerns.data && !rows.length ? t("designS9b.safeguarding.noCases") : undefined}
      aside={
        <SelectField
          label={t("safeguarding.status")}
          hideLabel
          size="sm"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          options={[
            { value: "", label: t("designS9b.safeguarding.anyStatus") },
            ...STATUSES.map((s) => ({ value: s, label: t(`safeguarding.statuses.${s}`) })),
          ]}
        />
      }
      columns={[
        { key: "ref", header: t("safeguarding.reference") },
        { key: "student", header: t("safeguarding.student") },
        { key: "category", header: t("safeguarding.category") },
        { key: "status", header: t("safeguarding.status") },
        { key: "raised", header: t("designS9b.safeguarding.raisedOn") },
      ]}
    >
      {rows.map((c) => (
        <tr key={c.id}>
          <Cell className="min-w-32">
            <Link to="/safeguarding/$concernId" params={{ concernId: c.id }} className={link}>
              {c.reference}
            </Link>
            {c.immediate_risk ? (
              <span className="block text-xs font-semibold text-margin">
                {t("safeguarding.immediateRisk")}
              </span>
            ) : null}
          </Cell>
          <Cell className="min-w-32">{c.student_name}</Cell>
          <Cell className="min-w-36">{t(`safeguarding.categories.${c.category}`)}</Cell>
          <Cell className={c.status === "closed" ? quiet : undefined}>
            {t(`safeguarding.statuses.${c.status}`)}
          </Cell>
          <Cell className="whitespace-nowrap tabular-nums">
            {formatDateTime(c.raised_at, i18n.language)}
          </Cell>
        </tr>
      ))}
    </Table>
  );
}

/** A case: what was raised, the timeline of actions, status, assignment and outcome.
 * Opening it is recorded in the case's own audit trail. */
export function ConcernPage({ concernId }: { concernId: string }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const concern = useQuery({
    queryKey: ["safeguarding", "concern", concernId],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/safeguarding/concerns/{id}", {
          params: { path: { id: concernId } },
        }),
      ),
  });
  const history = useQuery({
    queryKey: ["safeguarding", "history", concernId],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/safeguarding/concerns/{id}/history", {
          params: { path: { id: concernId } },
        }),
      ),
  });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["safeguarding"] });
  const [kind, setKind] = useState<string>("note");
  const [note, setNote] = useState("");
  const addAction = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/safeguarding/concerns/{id}/actions", {
          params: { path: { id: concernId } },
          body: { kind: kind as "note", note },
        }),
      ),
    onSuccess: () => {
      setNote("");
      refresh();
    },
  });
  const [outcome, setOutcome] = useState<string | null>(null);
  const update = useMutation({
    mutationFn: async (body: { status?: string; outcome?: string }) =>
      unwrap(
        await api.PATCH("/api/v1/safeguarding/concerns/{id}", {
          params: { path: { id: concernId } },
          body: body as { status?: "open" },
        }),
      ),
    onSuccess: refresh,
  });
  if (!concern.data) return <Spinner label={t("grid.loading")} />;
  const c: Concern = concern.data;
  const others = STATUSES.filter((s) => s !== c.status);
  return (
    <article className="max-w-3xl">
      <RecordHeader
        back={<Link to="/safeguarding">{t("safeguarding.title")}</Link>}
        title={`${c.reference} · ${t(`safeguarding.categories.${c.category}`)}`}
        description={
          <span className="tabular-nums">
            {t(`safeguarding.statuses.${c.status}`)} ·{" "}
            {t("safeguarding.raisedBy", {
              name: c.raised_by_name,
              date: formatDateTime(c.raised_at, i18n.language),
            })}
          </span>
        }
      />
      <div className="space-y-6">
        {c.immediate_risk ? (
          <Alert tone="danger">{t("safeguarding.immediateRiskAlert")}</Alert>
        ) : null}
        <RuledPanel flush titleId="what" title={t("safeguarding.whatHappened")}>
          <FactList items={[[t("safeguarding.student"), c.student_name ?? ""]]} />
          <p
            className={`px-5 py-4 text-sm whitespace-pre-wrap ${c.student_name ? "border-t border-rule" : ""}`}
          >
            {c.description}
          </p>
        </RuledPanel>
        <RuledPanel flush titleId="timeline" title={t("safeguarding.timeline")}>
          {c.actions.length ? (
            <PanelRows>
              {c.actions.map((a) => (
                <PanelRow
                  key={a.id}
                  className="grid gap-x-4 gap-y-0.5 sm:grid-cols-[9rem_minmax(0,1fr)]"
                >
                  <time
                    dateTime={a.occurred_at}
                    className="text-xs text-muted-foreground tabular-nums sm:pt-0.5"
                  >
                    {formatDateTime(a.occurred_at, i18n.language)}
                  </time>
                  <div className="min-w-0">
                    <p>
                      <span className="font-medium">{t(`safeguarding.actions.${a.kind}`)}</span>
                      <span className="text-muted-foreground"> · {a.actor_name}</span>
                    </p>
                    {a.note ? <p className="whitespace-pre-wrap">{a.note}</p> : null}
                  </div>
                </PanelRow>
              ))}
            </PanelRows>
          ) : (
            <p className="px-5 py-4 text-sm text-muted-foreground">
              {t("designS9b.safeguarding.noActions")}
            </p>
          )}
        </RuledPanel>
        <FormCard
          title={t("safeguarding.addAction")}
          submit={t("safeguarding.addActionSubmit")}
          pending={addAction.isPending}
          error={addAction.error}
          onSubmit={() => addAction.mutate()}
        >
          <SelectField
            label={t("safeguarding.actionKind")}
            value={kind}
            onChange={(e) => setKind(e.target.value)}
            options={ACTIONS.map((k) => ({ value: k, label: t(`safeguarding.actions.${k}`) }))}
          />
          <TextArea label={t("safeguarding.note")} value={note} onChange={setNote} />
        </FormCard>
        <RuledPanel
          flush
          titleId="status"
          title={t("safeguarding.statusAndOutcome")}
          aside={<span className={quiet}>{t(`safeguarding.statuses.${c.status}`)}</span>}
          footer={others.map((s) => (
            <Button
              key={s}
              variant={s === "closed" ? "primary" : "secondary"}
              disabled={update.isPending}
              className={s === "closed" ? "order-last" : undefined}
              onClick={() => update.mutate({ status: s, ...(outcome !== null ? { outcome } : {}) })}
            >
              {t(`safeguarding.moveTo.${s}`)}
            </Button>
          ))}
        >
          <div className="space-y-3 px-5 py-4">
            <TextAreaField
              label={t("safeguarding.outcome")}
              rows={4}
              value={outcome ?? c.outcome ?? ""}
              onChange={(e) => setOutcome(e.target.value)}
            />
            {update.error ? <Alert tone="danger">{update.error.message}</Alert> : null}
          </div>
        </RuledPanel>
        {history.data ? (
          <Disclosure summary={t("safeguarding.accessLog")}>
            <ul className="mt-2 divide-y divide-rule rounded-xl border border-border bg-surface text-sm">
              {history.data.map((h, i) => (
                <li key={i} className="px-5 py-2.5 tabular-nums">
                  {formatDateTime(h.at, i18n.language)} · {h.actor || t("safeguarding.system")} ·{" "}
                  {t(`designS9b.audit.actions.${h.action}`, { defaultValue: h.action })}
                </li>
              ))}
            </ul>
          </Disclosure>
        ) : null}
      </div>
    </article>
  );
}

function FlagsSection() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const flags = useQuery({
    queryKey: ["safeguarding", "flags"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/safeguarding/flags", {
          params: { query: { ...PAGE, status: "open" } },
        }),
      ),
  });
  const review = useMutation({
    mutationFn: async ({ id, decision }: { id: string; decision: "dismiss" | "escalate" }) =>
      unwrap(
        await api.POST("/api/v1/safeguarding/flags/{id}/review", {
          params: { path: { id } },
          body: { decision },
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["safeguarding"] }),
  });
  const rows = flags.data?.results ?? [];
  return (
    <RuledPanel
      flush
      title={t("safeguarding.tabs.flags")}
      rule={rows.length ? "margin" : "border"}
      aside={
        rows.length ? (
          <span className="font-semibold text-margin tabular-nums">
            {t("designS9b.safeguarding.waiting", { count: rows.length })}
          </span>
        ) : null
      }
    >
      {flags.isPending ? (
        <div className="px-5 py-4">
          <Spinner label={t("grid.loading")} />
        </div>
      ) : !rows.length ? (
        <p className="px-5 py-4 text-sm text-muted-foreground">{t("safeguarding.noFlags")}</p>
      ) : (
        <PanelRows>
          {rows.map((f) => (
            <PanelRow key={f.id} className="space-y-2">
              <div>
                <p className="font-medium tabular-nums">
                  {f.sender_name || t("safeguarding.unknownSender")} ·{" "}
                  {formatDateTime(f.created_at, i18n.language)}
                  {f.blocked ? ` · ${t("safeguarding.blocked")}` : ""}
                </p>
                <p className="text-xs text-muted-foreground">
                  {(f.reasons as string[])
                    .map((r) => t(`safeguarding.reasons.${r.split(":")[0]}`))
                    .join(", ")}
                  {(f.keywords as string[]).length
                    ? ` (${(f.keywords as string[]).join(", ")})`
                    : ""}
                </p>
              </div>
              <blockquote className="border-l border-border pl-3 whitespace-pre-wrap">
                {f.excerpt}
              </blockquote>
              <div className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={review.isPending}
                  onClick={() => review.mutate({ id: f.id, decision: "dismiss" })}
                >
                  {t("safeguarding.dismiss")}
                </Button>
                <Button
                  size="sm"
                  disabled={review.isPending}
                  onClick={() => review.mutate({ id: f.id, decision: "escalate" })}
                >
                  {t("safeguarding.escalate")}
                </Button>
              </div>
            </PanelRow>
          ))}
        </PanelRows>
      )}
      {review.error ? (
        <div className="px-5 pb-4">
          <Alert tone="danger">{review.error.message}</Alert>
        </div>
      ) : null}
    </RuledPanel>
  );
}

function LoneWorkingSection() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const [resolving, setResolving] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const visits = useQuery({
    queryKey: ["lone-working"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/lone-working/visits", { params: { query: PAGE } })),
  });
  const resolve = useMutation({
    mutationFn: async ({ id, note }: { id: string; note: string }) =>
      unwrap(
        await api.POST("/api/v1/lone-working/visits/{id}/resolve", {
          params: { path: { id } },
          body: { note },
        }),
      ),
    onSuccess: () => {
      setResolving(null);
      void queryClient.invalidateQueries({ queryKey: ["lone-working"] });
    },
  });
  const rows = visits.data?.results ?? [];
  const overdue = rows.filter((v) => v.status === "overdue").length;
  return (
    <div className="space-y-4">
      <Table
        caption={t("safeguarding.visits")}
        loading={visits.isPending}
        empty={visits.data && !rows.length ? t("designS9b.safeguarding.noVisits") : undefined}
        aside={
          overdue ? (
            <span className="font-semibold text-margin tabular-nums">
              {t("designS9b.safeguarding.overdueCount", { count: overdue })}
            </span>
          ) : null
        }
        columns={[
          { key: "tutor", header: t("safeguarding.tutorName") },
          { key: "lesson", header: t("safeguarding.lesson") },
          { key: "in", header: t("safeguarding.checkedIn") },
          { key: "status", header: t("safeguarding.status") },
          { key: "actions", header: t("common.actions", "Actions"), hidden: true },
        ]}
      >
        {rows.map((v) => (
          <tr key={v.id}>
            <Cell className="min-w-32 font-medium">{v.tutor_name}</Cell>
            <Cell className="min-w-40">{v.lesson_title}</Cell>
            <Cell className="whitespace-nowrap tabular-nums">
              {formatDateTime(v.checked_in_at, i18n.language)}
              <span className="block text-xs text-muted-foreground">
                {t("safeguarding.expectedEnd")}{" "}
                {formatDateTime(v.expected_end, i18n.language, undefined, { timeStyle: "short" })}
              </span>
            </Cell>
            <Cell
              className={
                v.status === "overdue"
                  ? "font-semibold text-margin"
                  : v.status === "checked_out" || v.status === "resolved"
                    ? quiet
                    : undefined
              }
            >
              {t(`safeguarding.visitStatuses.${v.status}`)}
            </Cell>
            <Cell className="py-1.5 text-right align-middle">
              {v.status === "overdue" || v.status === "checked_in" ? (
                resolving === v.id ? (
                  <form
                    className="flex flex-wrap items-center justify-end gap-2"
                    onKeyDown={(e) => {
                      if (e.key === "Escape") setResolving(null);
                    }}
                    onSubmit={(e) => {
                      e.preventDefault();
                      if (note.trim()) resolve.mutate({ id: v.id, note: note.trim() });
                    }}
                  >
                    <TextField
                      label={t("safeguarding.resolvePrompt")}
                      hideLabel
                      size="sm"
                      placeholder={t("safeguarding.resolvePrompt")}
                      className="min-w-64"
                      autoFocus
                      required
                      value={note}
                      onChange={(e) => setNote(e.target.value)}
                    />
                    <Button type="submit" size="sm" loading={resolve.isPending}>
                      {t("safeguarding.markSafe")}
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      className={quiet}
                      onClick={() => setResolving(null)}
                    >
                      {t("common.cancel")}
                    </Button>
                  </form>
                ) : (
                  <Button
                    size="sm"
                    variant="secondary"
                    className="whitespace-nowrap"
                    onClick={() => {
                      setNote("");
                      setResolving(v.id);
                    }}
                  >
                    {t("safeguarding.markSafe")}
                  </Button>
                )
              ) : null}
            </Cell>
          </tr>
        ))}
      </Table>
      {resolve.error ? <Alert tone="danger">{resolve.error.message}</Alert> : null}
    </div>
  );
}

/** Raise a concern (anyone with ``safeguarding.raise``): goes only to the DSLs. Its fields
 * and footer sit inside the panel that opens it. */
export function RaiseConcernForm({
  studentId,
  lessonId,
  onRaised,
  onCancel,
}: {
  studentId?: string;
  lessonId?: string;
  onRaised?: (reference: string) => void;
  onCancel?: () => void;
}) {
  const { t } = useTranslation();
  const [category, setCategory] = useState<string>("other");
  const [description, setDescription] = useState("");
  const [risk, setRisk] = useState(false);
  const raise = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/safeguarding/concerns", {
          body: {
            category: category as "other",
            description,
            immediate_risk: risk,
            ...(studentId ? { student: studentId } : {}),
            ...(lessonId ? { lesson: lessonId } : {}),
          },
        }),
      ),
    onSuccess: (data) => {
      setDescription("");
      setRisk(false);
      onRaised?.(data.reference);
    },
  });
  return (
    <form
      aria-label={t("safeguarding.raiseTitle")}
      className="border-t border-rule"
      onSubmit={(e) => {
        e.preventDefault();
        raise.mutate();
      }}
    >
      <div className="grid gap-x-4 gap-y-3 px-5 py-4 sm:grid-cols-2">
        <p className="text-sm text-muted-foreground sm:col-span-2">{t("safeguarding.raiseHint")}</p>
        <SelectField
          label={t("safeguarding.category")}
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          options={CATEGORIES.map((c) => ({ value: c, label: t(`safeguarding.categories.${c}`) }))}
        />
        <CheckboxField
          className="self-end pb-2.5"
          label={t("safeguarding.immediateRiskQuestion")}
          checked={risk}
          onChange={(e) => setRisk(e.target.checked)}
        />
        <TextArea
          label={t("safeguarding.description")}
          required
          value={description}
          onChange={setDescription}
          rows={6}
        />
        {risk ? (
          <Alert tone="warning" className="sm:col-span-2">
            {t("safeguarding.emergency")}
          </Alert>
        ) : null}
        {raise.error ? (
          <Alert tone="danger" className="sm:col-span-2">
            {raise.error.message}
          </Alert>
        ) : null}
        {raise.isSuccess ? (
          <Alert tone="success" className="sm:col-span-2">
            {t("safeguarding.raised", { reference: raise.data.reference })}
          </Alert>
        ) : null}
      </div>
      <PanelFooter>
        <Button type="submit" loading={raise.isPending}>
          {t("safeguarding.raiseSubmit")}
        </Button>
        {onCancel ? (
          <Button type="button" variant="ghost" className={quiet} onClick={onCancel}>
            {t("common.cancel")}
          </Button>
        ) : null}
      </PanelFooter>
    </form>
  );
}

/** On the student page: the age-aware privacy defaults and "raise a concern". */
export function StudentPrivacyPanel({ studentId }: { studentId: string }) {
  const { t } = useTranslation();
  const canRaise = usePermission("safeguarding.raise");
  const [open, setOpen] = useState(false);
  const privacy = useQuery({
    queryKey: ["students", studentId, "privacy"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/students/{student_id}/privacy", {
          params: { path: { student_id: studentId } },
        }),
      ),
    retry: false,
  });
  const lines = privacy.data
    ? [
        privacy.data.is_child ? t("safeguarding.childDefaults") : null,
        privacy.data.coppa_applies
          ? privacy.data.parental_consent
            ? t("safeguarding.coppaConsented")
            : t("safeguarding.coppaNeeded")
          : null,
        !privacy.data.is_child ? t("safeguarding.adultLearner") : null,
      ].filter((line): line is string => Boolean(line))
    : [];
  return (
    <RuledPanel
      flush
      titleId="student-privacy"
      title={t("safeguarding.privacyAndSafeguarding")}
      footer={
        canRaise && !open ? (
          <Button size="sm" variant="secondary" onClick={() => setOpen(true)}>
            {t("safeguarding.raiseButton")}
          </Button>
        ) : undefined
      }
    >
      {lines.length ? (
        <PanelRows>
          {lines.map((line) => (
            <PanelRow key={line}>{line}</PanelRow>
          ))}
        </PanelRows>
      ) : null}
      {canRaise && open ? (
        <RaiseConcernForm studentId={studentId} onCancel={() => setOpen(false)} />
      ) : null}
    </RuledPanel>
  );
}
