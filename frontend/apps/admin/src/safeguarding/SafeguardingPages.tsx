import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, Tabs } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { api, usePermission } from "../api";
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

const link = "text-primary underline-offset-2 hover:underline";

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
    <section>
      <h1 className="mb-1 text-2xl font-semibold">{t("safeguarding.title")}</h1>
      <p className="mb-4 text-sm text-muted-foreground">{t("safeguarding.confidential")}</p>
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
  return (
    <div className="space-y-4">
      <SelectField
        label={t("safeguarding.status")}
        value={status}
        onChange={(e) => setStatus(e.target.value)}
        options={[
          { value: "", label: t("safeguarding.allStatuses") },
          ...STATUSES.map((s) => ({ value: s, label: t(`safeguarding.statuses.${s}`) })),
        ]}
      />
      {concerns.data ? (
        <Table
          caption={t("safeguarding.cases")}
          headers={[
            t("safeguarding.reference"),
            t("safeguarding.student"),
            t("safeguarding.category"),
            t("safeguarding.status"),
            t("safeguarding.raised"),
          ]}
        >
          {concerns.data.results.map((c) => (
            <tr key={c.id}>
              <Cell>
                <Link to="/safeguarding/$concernId" params={{ concernId: c.id }} className={link}>
                  {c.reference}
                </Link>
                {c.immediate_risk ? (
                  <span className="ml-2 rounded bg-destructive px-1 text-xs text-destructive-foreground">
                    {t("safeguarding.immediateRisk")}
                  </span>
                ) : null}
              </Cell>
              <Cell>{c.student_name}</Cell>
              <Cell>{t(`safeguarding.categories.${c.category}`)}</Cell>
              <Cell>{t(`safeguarding.statuses.${c.status}`)}</Cell>
              <Cell>{formatDateTime(c.raised_at, i18n.language)}</Cell>
            </tr>
          ))}
        </Table>
      ) : (
        <Spinner className="size-5" label={t("grid.loading")} />
      )}
    </div>
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
  if (!concern.data) return <Spinner className="size-5" label={t("grid.loading")} />;
  const c: Concern = concern.data;
  return (
    <article className="space-y-6">
      <p className="text-sm">
        <Link to="/safeguarding" className={link}>
          {t("safeguarding.title")}
        </Link>
      </p>
      <header>
        <h1 className="text-2xl font-semibold">
          {c.reference} · {t(`safeguarding.categories.${c.category}`)}
        </h1>
        <p className="text-sm text-muted-foreground">
          {t(`safeguarding.statuses.${c.status}`)} ·{" "}
          {t("safeguarding.raisedBy", {
            name: c.raised_by_name,
            date: formatDateTime(c.raised_at, i18n.language),
          })}
        </p>
        {c.immediate_risk ? (
          <Alert tone="danger">{t("safeguarding.immediateRiskAlert")}</Alert>
        ) : null}
      </header>
      <section aria-labelledby="what" className="rounded-md border border-border p-4">
        <h2 id="what" className="mb-2 font-semibold">
          {t("safeguarding.whatHappened")}
        </h2>
        {c.student_name ? (
          <p className="mb-2 text-sm">
            {t("safeguarding.student")}: {c.student_name}
          </p>
        ) : null}
        <p className="whitespace-pre-wrap text-sm">{c.description}</p>
      </section>
      <section aria-labelledby="timeline" className="space-y-3">
        <h2 id="timeline" className="font-semibold">
          {t("safeguarding.timeline")}
        </h2>
        <ol className="space-y-2 border-l border-border pl-4">
          {c.actions.map((a) => (
            <li key={a.id} className="text-sm">
              <p className="font-medium">
                {t(`safeguarding.actions.${a.kind}`)} · {a.actor_name} ·{" "}
                {formatDateTime(a.occurred_at, i18n.language)}
              </p>
              {a.note ? <p className="whitespace-pre-wrap">{a.note}</p> : null}
            </li>
          ))}
        </ol>
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
      </section>
      <section aria-labelledby="status" className="space-y-3 rounded-md border border-border p-4">
        <h2 id="status" className="font-semibold">
          {t("safeguarding.statusAndOutcome")}
        </h2>
        <TextArea
          label={t("safeguarding.outcome")}
          value={outcome ?? c.outcome ?? ""}
          onChange={setOutcome}
        />
        <div className="flex flex-wrap gap-2">
          {STATUSES.filter((s) => s !== c.status).map((s) => (
            <Button
              key={s}
              variant={s === "closed" ? "danger" : "secondary"}
              disabled={update.isPending}
              onClick={() => update.mutate({ status: s, ...(outcome !== null ? { outcome } : {}) })}
            >
              {t(`safeguarding.moveTo.${s}`)}
            </Button>
          ))}
        </div>
        {update.error ? <Alert tone="danger">{update.error.message}</Alert> : null}
      </section>
      {history.data ? (
        <details className="text-sm">
          <summary className="cursor-pointer font-medium">{t("safeguarding.accessLog")}</summary>
          <ul className="mt-2 space-y-1">
            {history.data.map((h, i) => (
              <li key={i}>
                {formatDateTime(h.at, i18n.language)} · {h.actor || t("safeguarding.system")} ·{" "}
                {h.action}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
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
  if (!flags.data) return <Spinner className="size-5" label={t("grid.loading")} />;
  if (!flags.data.results.length) return <p>{t("safeguarding.noFlags")}</p>;
  return (
    <ul className="space-y-3">
      {flags.data.results.map((f) => (
        <li key={f.id} className="rounded-md border border-border p-3 text-sm">
          <p className="font-medium">
            {f.sender_name || t("safeguarding.unknownSender")} ·{" "}
            {formatDateTime(f.created_at, i18n.language)}
            {f.blocked ? ` · ${t("safeguarding.blocked")}` : ""}
          </p>
          <p className="text-muted-foreground">
            {(f.reasons as string[])
              .map((r) => t(`safeguarding.reasons.${r.split(":")[0]}`))
              .join(", ")}
            {(f.keywords as string[]).length ? ` (${(f.keywords as string[]).join(", ")})` : ""}
          </p>
          <blockquote className="my-2 border-l-2 border-border pl-3 whitespace-pre-wrap">
            {f.excerpt}
          </blockquote>
          <div className="flex gap-2">
            <Button
              size="sm"
              variant="secondary"
              onClick={() => review.mutate({ id: f.id, decision: "dismiss" })}
            >
              {t("safeguarding.dismiss")}
            </Button>
            <Button
              size="sm"
              variant="danger"
              onClick={() => review.mutate({ id: f.id, decision: "escalate" })}
            >
              {t("safeguarding.escalate")}
            </Button>
          </div>
        </li>
      ))}
    </ul>
  );
}

function LoneWorkingSection() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
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
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["lone-working"] }),
  });
  if (!visits.data) return <Spinner className="size-5" label={t("grid.loading")} />;
  return (
    <Table
      caption={t("safeguarding.visits")}
      headers={[
        t("safeguarding.tutorName"),
        t("safeguarding.lesson"),
        t("safeguarding.checkedIn"),
        t("safeguarding.expectedEnd"),
        t("safeguarding.status"),
        "",
      ]}
    >
      {visits.data.results.map((v) => (
        <tr key={v.id}>
          <Cell>{v.tutor_name}</Cell>
          <Cell>{v.lesson_title}</Cell>
          <Cell>{formatDateTime(v.checked_in_at, i18n.language)}</Cell>
          <Cell>{formatDateTime(v.expected_end, i18n.language)}</Cell>
          <Cell>
            <span className={v.status === "overdue" ? "font-semibold text-destructive" : ""}>
              {t(`safeguarding.visitStatuses.${v.status}`)}
            </span>
          </Cell>
          <Cell>
            {v.status === "overdue" || v.status === "checked_in" ? (
              <Button
                size="sm"
                variant="secondary"
                onClick={() => {
                  const note = window.prompt(t("safeguarding.resolvePrompt")) ?? "";
                  if (note) resolve.mutate({ id: v.id, note });
                }}
              >
                {t("safeguarding.markSafe")}
              </Button>
            ) : null}
          </Cell>
        </tr>
      ))}
    </Table>
  );
}

/** Raise a concern (anyone with ``safeguarding.raise``): goes only to the DSLs. */
export function RaiseConcernForm({
  studentId,
  lessonId,
  onRaised,
}: {
  studentId?: string;
  lessonId?: string;
  onRaised?: (reference: string) => void;
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
    <div className="space-y-2">
      <FormCard
        title={t("safeguarding.raiseTitle")}
        submit={t("safeguarding.raiseSubmit")}
        pending={raise.isPending}
        error={raise.error}
        onSubmit={() => raise.mutate()}
      >
        <p className="text-sm text-muted-foreground sm:col-span-2">{t("safeguarding.raiseHint")}</p>
        <SelectField
          label={t("safeguarding.category")}
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          options={CATEGORIES.map((c) => ({ value: c, label: t(`safeguarding.categories.${c}`) }))}
        />
        <label className="flex items-center gap-2 self-end text-sm">
          <input type="checkbox" checked={risk} onChange={(e) => setRisk(e.target.checked)} />
          {t("safeguarding.immediateRiskQuestion")}
        </label>
        <TextArea
          label={t("safeguarding.description")}
          required
          value={description}
          onChange={setDescription}
          rows={6}
        />
      </FormCard>
      {raise.isSuccess ? (
        <Alert tone="success">
          {t("safeguarding.raised", { reference: raise.data.reference })}
        </Alert>
      ) : null}
      {risk ? <Alert tone="warning">{t("safeguarding.emergency")}</Alert> : null}
    </div>
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
  return (
    <section aria-labelledby="student-privacy" className="mt-4 space-y-3">
      <h2 id="student-privacy" className="font-semibold">
        {t("safeguarding.privacyAndSafeguarding")}
      </h2>
      {privacy.data ? (
        <ul className="list-inside list-disc text-sm">
          {privacy.data.is_child ? <li>{t("safeguarding.childDefaults")}</li> : null}
          {privacy.data.coppa_applies ? (
            <li>
              {privacy.data.parental_consent
                ? t("safeguarding.coppaConsented")
                : t("safeguarding.coppaNeeded")}
            </li>
          ) : null}
          {!privacy.data.is_child ? <li>{t("safeguarding.adultLearner")}</li> : null}
        </ul>
      ) : null}
      {canRaise ? (
        open ? (
          <RaiseConcernForm studentId={studentId} />
        ) : (
          <Button variant="secondary" onClick={() => setOpen(true)}>
            {t("safeguarding.raiseButton")}
          </Button>
        )
      ) : null}
    </section>
  );
}
