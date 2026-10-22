import { unwrap } from "@tutortrack/api-client";
import { formatDate, formatDateTime, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  FactList,
  NamePlate,
  PageHeader,
  Panel,
  PanelFooter,
  PanelRow,
  PanelRows,
  SelectField,
  Spinner,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useId, useState, type ReactNode } from "react";

import { api, usePermission } from "../api";
import { AiJobAdvert } from "../ai/AiWidgets";
import { AttachedFiles } from "../components/AttachedFiles";
import { HeaderReveal, RecordHeader, RecordLayout } from "../components/RecordHeader";
import { TabLinks } from "../components/TabLinks";
import { Turnstile } from "../components/Turnstile";
import { PublicLayout } from "../layout/PublicLayout";
import { PublicField, type Schema } from "../leads/MorePages";

/** The recruitment area's frame: page header and the Applications / Openings / Compliance
 * links (G5a adds Openings), ruled like tabs. */
export function RecruitmentPage({
  title,
  description,
  actions,
  children,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <div>
      <PageHeader title={title} description={description} actions={actions} className="mb-4" />
      <TabLinks
        label={t("recruitment.title")}
        className="mb-6"
        links={[
          { to: "/recruitment", label: t("recruitment.applications"), exact: true },
          { to: "/recruitment/openings", label: t("hiring.openings.title") },
          { to: "/compliance", label: t("recruitment.compliance") },
        ]}
      />
      <div className="space-y-6">{children}</div>
    </div>
  );
}

const Page = RecruitmentPage;

const subjectList = (subjects: unknown) =>
  ((subjects as { subject: string }[] | undefined) ?? []).map((s) => s.subject).join(", ");

/** Applications by stage (FR-18-2): the open stages as ruled columns. */
export function ApplicationsPage() {
  const { t } = useTranslation();
  const canManageOpenings = usePermission("recruitment.pipeline.manage");
  const stages = useQuery({
    queryKey: ["application-stages"],
    queryFn: async () => unwrap(await api.GET("/api/v1/application-stages")),
  });
  const applications = useQuery({
    queryKey: ["applications", "open"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/applications", {
          params: { query: { status: "open", page_size: 200 } },
        }),
      ),
  });
  return (
    <Page title={t("recruitment.title")}>
      {applications.isPending || stages.isPending ? <Spinner label={t("grid.loading")} /> : null}
      {/* Scrolls sideways when the stages outgrow the page: focusable so keyboards can scroll it. */}
      <div
        role="region"
        aria-label={t("recruitment.applications")}
        tabIndex={0}
        className="relative flex items-start gap-4 overflow-x-auto pb-2"
      >
        {stages.data
          ?.filter((s) => s.kind === "open")
          .map((stage) => {
            const cards = applications.data?.results.filter((a) => a.stage === stage.id) ?? [];
            return (
              <section
                key={stage.id}
                aria-label={stage.name}
                className="w-72 shrink-0 rounded-xl border border-border bg-surface"
              >
                <h2 className="flex items-baseline justify-between gap-2 border-b border-border px-4 py-3 text-base font-semibold">
                  <span className="min-w-0 truncate">{stage.name}</span>
                  <span className="text-sm font-normal text-muted-foreground tabular-nums">
                    {cards.length}
                  </span>
                </h2>
                {cards.length ? (
                  <ul className="divide-y divide-rule">
                    {cards.map((a) => (
                      <li key={a.id} className="px-4 py-2.5 text-sm hover:bg-muted/60">
                        <NamePlate
                          name={
                            <Link
                              to="/recruitment/$id"
                              params={{ id: a.id }}
                              className="underline-offset-2 hover:underline"
                            >
                              {a.full_name}
                            </Link>
                          }
                          context={[
                            subjectList(a.subjects),
                            a.opening_title,
                            formatDate(a.created_at),
                          ]
                            .filter(Boolean)
                            .join(" · ")}
                        />
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="px-4 py-4 text-sm text-muted-foreground">
                    {t("designS8.recruitment.emptyColumn")}
                  </p>
                )}
              </section>
            );
          })}
      </div>
      {canManageOpenings ? <AiJobAdvert /> : null}
    </Page>
  );
}

/** One application: what they sent, next steps (interview, references), the decision, and
 * its references, interviews and scorecards beside it. */
export function ApplicationPage({ id }: { id: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canDecide = usePermission("recruitment.application.decide");
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [referee, setReferee] = useState({ name: "", email: "" });
  const [slot, setSlot] = useState("");
  const [inviteMode, setInviteMode] = useState<"availability" | "times">("availability");
  const [windowStart, setWindowStart] = useState("");
  const [windowEnd, setWindowEnd] = useState("");
  const [minutes, setMinutes] = useState("30");
  const [stage, setStage] = useState("");
  const application = useQuery({
    queryKey: ["application", id],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/applications/{id}", { params: { path: { id } } })),
  });
  const stages = useQuery({
    queryKey: ["application-stages"],
    queryFn: async () => unwrap(await api.GET("/api/v1/application-stages")),
  });
  const path = { params: { path: { id } } };
  const set = (data: unknown) => queryClient.setQueryData(["application", id], data);
  const move = useMutation({
    mutationFn: async (stage: string) =>
      unwrap(await api.POST("/api/v1/applications/{id}/move", { ...path, body: { stage } })),
    onSuccess: set,
  });
  const approve = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/applications/{id}/approve", {
          ...path,
          body: { employment_type: "self_employed" },
        }),
      ),
    onSuccess: set,
  });
  const reject = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/applications/{id}/reject", {
          ...path,
          body: { reason, talent_pool: false, notify: true },
        }),
      ),
    onSuccess: (data) => {
      set(data);
      setRejecting(false);
    },
  });
  const reference = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/applications/{id}/references", {
          ...path,
          body: { ...referee, relationship: "" },
        }),
      ),
    onSuccess: (data) => {
      set(data);
      setReferee({ name: "", email: "" });
    },
  });
  const interview = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/applications/{id}/interviews", {
          ...path,
          body:
            inviteMode === "availability"
              ? {
                  mode: "availability",
                  window_start: windowStart,
                  window_end: windowEnd || windowStart,
                  minutes: Number(minutes),
                  options: [],
                  meeting_url: "",
                }
              : {
                  mode: "times",
                  options: [new Date(slot).toISOString()],
                  minutes: Number(minutes),
                  meeting_url: "",
                },
        }),
      ),
    onSuccess: set,
  });
  if (!application.data) return <Spinner label={t("grid.loading")} />;
  const a = application.data;
  const open = a.status === "open";
  const openStages = stages.data?.filter((s) => s.kind === "open") ?? [];
  const error = move.error ?? approve.error ?? reference.error ?? interview.error;
  const files = [
    ...(a.cv_file
      ? [{ ...a.cv_file, filename: `${t("hiring.files.cv")}: ${a.cv_file.filename}` }]
      : []),
    ...(a.video_file
      ? [{ ...a.video_file, filename: `${t("hiring.files.video")}: ${a.video_file.filename}` }]
      : []),
    ...(a.attachments ?? []),
  ];
  return (
    <article>
      <RecordHeader
        back={<Link to="/recruitment">{t("recruitment.applications")}</Link>}
        title={a.full_name}
        description={[
          open ? a.stage_name : t(`recruitment.status.${a.status}`),
          a.opening_title,
          t("designS8.recruitment.applied", { date: formatDate(a.created_at) }),
        ]
          .filter(Boolean)
          .join(" · ")}
        actions={
          open ? (
            <>
              {openStages.length > 1 ? (
                <HeaderReveal label={t("designS8.recruitment.moveStage")}>
                  {(close) => (
                    <>
                      <SelectField
                        label={t("recruitment.stage")}
                        hideLabel
                        size="sm"
                        value={stage || a.stage}
                        onChange={(e) => setStage(e.target.value)}
                        options={openStages.map((s) => ({ value: s.id, label: s.name }))}
                      />
                      <Button
                        size="sm"
                        loading={move.isPending}
                        onClick={() => move.mutate(stage || a.stage, { onSuccess: () => close() })}
                      >
                        {t("designS8.recruitment.move")}
                      </Button>
                    </>
                  )}
                </HeaderReveal>
              ) : null}
              {canDecide ? (
                <>
                  <Button size="sm" onClick={() => approve.mutate()} loading={approve.isPending}>
                    {t("recruitment.approve")}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-muted-foreground"
                    aria-expanded={rejecting}
                    onClick={() => setRejecting(true)}
                  >
                    {t("recruitment.reject")}
                  </Button>
                </>
              ) : null}
            </>
          ) : null
        }
      />
      {error ? (
        <Alert tone="danger" className="mb-6">
          {error.message}
        </Alert>
      ) : null}
      <RecordLayout
        main={
          <>
            {rejecting && open && canDecide ? (
              <Panel flush title={t("designS8.recruitment.rejectTitle")}>
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    reject.mutate();
                  }}
                >
                  <div className="max-w-md px-5 py-4">
                    <TextField
                      label={t("recruitment.rejectReason")}
                      required
                      value={reason}
                      onChange={(e) => setReason(e.target.value)}
                    />
                  </div>
                  {reject.error ? (
                    <Alert tone="danger" className="mx-5 mb-4">
                      {reject.error.message}
                    </Alert>
                  ) : null}
                  <PanelFooter>
                    <Button
                      type="submit"
                      size="sm"
                      variant="danger"
                      disabled={!reason.trim()}
                      loading={reject.isPending}
                    >
                      {t("recruitment.reject")}
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setRejecting(false)}>
                      {t("common.cancel")}
                    </Button>
                  </PanelFooter>
                </form>
              </Panel>
            ) : null}
            <Panel title={t("designS8.recruitment.application")} flush>
              <FactList
                none={t("designS5.noDetails")}
                items={[
                  [t("recruitment.subjects"), subjectList(a.subjects)],
                  [t("designS8.recruitment.qualifications"), a.qualifications],
                  [
                    t("designS8.recruitment.experience"),
                    a.experience ? <span className="whitespace-pre-line">{a.experience}</span> : "",
                  ],
                  ...Object.entries(a.answers as Record<string, unknown>).map(
                    ([q, v]) => [q, String(v ?? "")] as const,
                  ),
                  [
                    t("hiring.files.videoLink"),
                    a.video_url ? (
                      <a
                        className="text-link underline-offset-2 hover:underline"
                        href={a.video_url}
                        rel="noreferrer"
                        target="_blank"
                      >
                        {a.video_url}
                      </a>
                    ) : (
                      ""
                    ),
                  ],
                  [t("hiring.files.uploads"), files.length ? <AttachedFiles files={files} /> : ""],
                ]}
              />
            </Panel>
            {open ? (
              <NextSteps
                inviteMode={inviteMode}
                setInviteMode={setInviteMode}
                minutes={minutes}
                setMinutes={setMinutes}
                windowStart={windowStart}
                setWindowStart={setWindowStart}
                windowEnd={windowEnd}
                setWindowEnd={setWindowEnd}
                slot={slot}
                setSlot={setSlot}
                invitePending={interview.isPending}
                onInvite={() => interview.mutate()}
                referee={referee}
                setReferee={setReferee}
                referencePending={reference.isPending}
                onReference={() => reference.mutate()}
              />
            ) : null}
          </>
        }
        side={
          <>
            <Panel title={t("people.details")} flush>
              <FactList
                items={[
                  [t("people.email"), a.email],
                  [t("people.phone"), a.phone],
                  [t("designS8.recruitment.postcode"), a.postcode],
                  [t("designS8.recruitment.rightToWork"), a.right_to_work],
                ]}
                none={t("designS5.noDetails")}
              />
            </Panel>
            <Panel title={t("recruitment.interviews")} flush>
              {a.interviews.length ? (
                <PanelRows>
                  {a.interviews.map((i) => (
                    <PanelRow key={i.id}>
                      <NamePlate
                        name={
                          i.start ? (
                            <span className="tabular-nums">{formatDateTime(i.start)}</span>
                          ) : (
                            t("recruitment.awaitingChoice")
                          )
                        }
                        context={
                          i.mode === "availability" && !i.start && i.window_start
                            ? t("hiring.interviews.window", {
                                from: formatDate(i.window_start),
                                to: formatDate(i.window_end ?? i.window_start),
                              })
                            : undefined
                        }
                        aside={
                          i.host_url || i.meeting_url ? (
                            <a
                              className="text-link underline-offset-2 hover:underline"
                              href={i.host_url || i.meeting_url}
                              target="_blank"
                              rel="noreferrer"
                            >
                              {t("hiring.interviews.join")}
                            </a>
                          ) : null
                        }
                      />
                    </PanelRow>
                  ))}
                </PanelRows>
              ) : (
                <p className="px-5 py-4 text-sm text-muted-foreground">
                  {t("designS8.recruitment.noInterviews")}
                </p>
              )}
            </Panel>
            <Panel title={t("recruitment.references")} flush>
              {a.references.length ? (
                <PanelRows>
                  {a.references.map((r) => (
                    <PanelRow key={r.id}>
                      <NamePlate
                        name={r.referee_name}
                        context={[
                          t(`recruitment.referenceStatus.${r.status}`),
                          r.rating ? t("designS8.recruitment.rating", { rating: r.rating }) : "",
                        ]
                          .filter(Boolean)
                          .join(" · ")}
                        aside={
                          r.concerns ? (
                            <span className="text-sm font-semibold text-margin">
                              {t("recruitment.concerns")}
                            </span>
                          ) : null
                        }
                      />
                    </PanelRow>
                  ))}
                </PanelRows>
              ) : (
                <p className="px-5 py-4 text-sm text-muted-foreground">
                  {t("designS8.recruitment.noReferences")}
                </p>
              )}
            </Panel>
            <Panel title={t("recruitment.scorecards")} flush>
              {a.scorecards.length ? (
                <PanelRows>
                  {a.scorecards.map((sc) => (
                    <PanelRow key={sc.id}>
                      <NamePlate
                        name={sc.reviewer_name}
                        context={sc.stage_name}
                        aside={
                          <span className="text-sm">
                            {t(`recruitment.recommendations.${sc.recommendation}`)}
                          </span>
                        }
                      />
                    </PanelRow>
                  ))}
                </PanelRows>
              ) : (
                <p className="px-5 py-4 text-sm text-muted-foreground">
                  {t("designS8.recruitment.noScorecards")}
                </p>
              )}
            </Panel>
          </>
        }
      />
    </article>
  );
}

/** Invite to an interview and ask for a reference: each a ruled row of fields and the button
 * they enable. */
function NextSteps(props: {
  inviteMode: "availability" | "times";
  setInviteMode: (v: "availability" | "times") => void;
  minutes: string;
  setMinutes: (v: string) => void;
  windowStart: string;
  setWindowStart: (v: string) => void;
  windowEnd: string;
  setWindowEnd: (v: string) => void;
  slot: string;
  setSlot: (v: string) => void;
  invitePending: boolean;
  onInvite: () => void;
  referee: { name: string; email: string };
  setReferee: (v: { name: string; email: string }) => void;
  referencePending: boolean;
  onReference: () => void;
}) {
  const { t } = useTranslation();
  const inviteId = useId();
  const p = props;
  return (
    <Panel title={t("designS8.recruitment.nextSteps")} flush>
      <div className="divide-y divide-rule">
        <div className="px-5 py-4">
          <fieldset className="space-y-3" aria-describedby={`${inviteId}-hint`}>
            <legend className="mb-3 text-sm font-semibold">
              {t("recruitment.inviteToInterview")}
            </legend>
            <div className="grid gap-3 sm:grid-cols-2">
              <SelectField
                label={t("hiring.interviews.how")}
                value={p.inviteMode}
                onChange={(e) => p.setInviteMode(e.target.value as "availability" | "times")}
                options={[
                  { value: "availability", label: t("hiring.interviews.bookingLink") },
                  { value: "times", label: t("hiring.interviews.oneTime") },
                ]}
              />
              <SelectField
                label={t("hiring.interviews.length")}
                value={p.minutes}
                onChange={(e) => p.setMinutes(e.target.value)}
                options={["20", "30", "45", "60"].map((m) => ({
                  value: m,
                  label: t("hiring.interviews.minutes", { count: Number(m) }),
                }))}
              />
              {p.inviteMode === "availability" ? (
                <>
                  <TextField
                    label={t("hiring.interviews.from")}
                    type="date"
                    value={p.windowStart}
                    onChange={(e) => p.setWindowStart(e.target.value)}
                  />
                  <TextField
                    label={t("hiring.interviews.to")}
                    type="date"
                    value={p.windowEnd}
                    onChange={(e) => p.setWindowEnd(e.target.value)}
                  />
                </>
              ) : (
                <TextField
                  label={t("recruitment.interviewTime")}
                  type="datetime-local"
                  value={p.slot}
                  onChange={(e) => p.setSlot(e.target.value)}
                />
              )}
            </div>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
              <Button
                size="sm"
                variant="secondary"
                disabled={p.inviteMode === "availability" ? !p.windowStart : !p.slot}
                loading={p.invitePending}
                onClick={p.onInvite}
              >
                {t("hiring.interviews.send")}
              </Button>
              <p id={`${inviteId}-hint`} className="text-xs text-muted-foreground">
                {t("hiring.interviews.hint")}
              </p>
            </div>
          </fieldset>
        </div>
        <div className="px-5 py-4">
          <fieldset className="space-y-3">
            <legend className="mb-3 text-sm font-semibold">
              {t("recruitment.requestReference")}
            </legend>
            <div className="grid gap-3 sm:grid-cols-2">
              <TextField
                label={t("recruitment.refereeName", { n: "" })}
                value={p.referee.name}
                onChange={(e) => p.setReferee({ ...p.referee, name: e.target.value })}
              />
              <TextField
                label={t("recruitment.refereeEmail", { n: "" })}
                type="email"
                value={p.referee.email}
                onChange={(e) => p.setReferee({ ...p.referee, email: e.target.value })}
              />
            </div>
            <Button
              size="sm"
              variant="secondary"
              disabled={!p.referee.email}
              loading={p.referencePending}
              onClick={p.onReference}
            >
              {t("designS8.recruitment.sendRequest")}
            </Button>
          </fieldset>
        </div>
      </div>
    </Panel>
  );
}

/** How a compliance cell reads: overdue and to-check in margin red, gaps in faded ink. */
const CELL_TONE: Record<string, string> = {
  verified: "",
  submitted: "font-semibold text-margin",
  expired: "font-semibold text-margin",
  missing: "text-muted-foreground",
  rejected: "font-medium",
};

/** Tutors × requirements (FR-18-8), with filters, CSV export and bulk "request missing
 * documents" (gap batch G5a). */
export function ComplianceDashboardPage() {
  const { t } = useTranslation();
  const canRequest = usePermission("compliance.verify");
  const [tutorStatus, setTutorStatus] = useState("");
  const [requirement, setRequirement] = useState("");
  const [gaps, setGaps] = useState(false);
  const [selected, setSelected] = useState<string[]>([]);
  const query = {
    ...(tutorStatus ? { tutor_status: tutorStatus as "onboarding" | "active" | "restricted" } : {}),
    ...(requirement ? { requirement } : {}),
    ...(gaps ? { gaps: true } : {}),
  };
  const board = useQuery({
    queryKey: ["compliance-dashboard", query],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/compliance/dashboard", { params: { query } })),
  });
  const types = useQuery({
    queryKey: ["requirement-types"],
    queryFn: async () => unwrap(await api.GET("/api/v1/compliance/requirement-types")),
  });
  const exportCsv = useMutation({
    mutationFn: async () => {
      const result = await api.GET("/api/v1/compliance/dashboard/export", {
        params: { query },
        parseAs: "blob",
      });
      const response = result.response as Response;
      if (!response.ok || !result.data) throw new Error(t("hiring.compliance.exportFailed"));
      const url = URL.createObjectURL(result.data as unknown as Blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "compliance.csv";
      link.click();
      URL.revokeObjectURL(url);
    },
  });
  const request = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/compliance/request-missing", {
          body: {
            tutors: selected.length ? selected : (board.data?.rows.map((r) => r.tutor) ?? []),
            requirements: requirement ? [requirement] : [],
          },
        }),
      ),
    onSuccess: () => setSelected([]),
  });
  const toggle = (id: string) =>
    setSelected(selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id]);
  return (
    <Page
      title={t("recruitment.compliance")}
      actions={
        <>
          <Button
            size="sm"
            variant="secondary"
            loading={exportCsv.isPending}
            onClick={() => exportCsv.mutate()}
          >
            {t("hiring.compliance.export")}
          </Button>
          {canRequest ? (
            <Button loading={request.isPending} onClick={() => request.mutate()}>
              {selected.length
                ? t("hiring.compliance.requestSelected", { count: selected.length })
                : t("hiring.compliance.requestAll")}
            </Button>
          ) : null}
        </>
      }
    >
      <div
        className="-mt-2 flex flex-wrap items-center gap-2"
        role="group"
        aria-label={t("hiring.compliance.filters")}
      >
        <SelectField
          label={t("hiring.compliance.tutorStatus")}
          hideLabel
          size="sm"
          value={tutorStatus}
          onChange={(e) => setTutorStatus(e.target.value)}
          options={[
            { value: "", label: t("hiring.compliance.anyStatus") },
            ...["onboarding", "active", "restricted"].map((v) => ({
              value: v,
              label: t(`people.tutorStatus.${v}`),
            })),
          ]}
        />
        <SelectField
          label={t("hiring.compliance.requirement")}
          hideLabel
          size="sm"
          value={requirement}
          onChange={(e) => setRequirement(e.target.value)}
          options={[
            { value: "", label: t("hiring.compliance.allRequirements") },
            ...(types.data ?? [])
              .filter((r) => r.active)
              .map((r) => ({ value: r.key, label: r.name })),
          ]}
        />
        <label className="flex h-9 items-center gap-2 px-1 text-sm">
          <input
            type="checkbox"
            className="size-4"
            checked={gaps}
            onChange={(e) => setGaps(e.target.checked)}
          />
          {t("hiring.compliance.gapsOnly")}
        </label>
      </div>
      {request.isSuccess ? (
        <Alert tone="success">
          {t("hiring.compliance.requested", { count: request.data.count })}
        </Alert>
      ) : null}
      {(request.error ?? exportCsv.error) ? (
        <Alert tone="danger">{(request.error ?? exportCsv.error)?.message}</Alert>
      ) : null}
      {!board.data ? (
        <Spinner label={t("grid.loading")} />
      ) : (
        <div
          role="region"
          aria-label={t("recruitment.compliance")}
          tabIndex={0}
          className="relative overflow-x-auto rounded-xl border border-border bg-surface"
        >
          <table className="w-full text-sm">
            <caption className="sr-only">{t("recruitment.compliance")}</caption>
            <thead>
              <tr className="border-b border-border">
                {canRequest ? (
                  <th scope="col" className="w-10 py-2.5 pl-4">
                    <span className="sr-only">{t("hiring.compliance.select")}</span>
                  </th>
                ) : null}
                <th scope="col" className="px-4 py-2.5 whitespace-nowrap">
                  {t("recruitment.tutor")}
                </th>
                {board.data.requirements.map((r) => (
                  <th key={r.key} scope="col" className="px-4 py-2.5 whitespace-nowrap">
                    {r.name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {board.data.rows.map((row) => (
                <tr key={row.tutor}>
                  {canRequest ? (
                    <td className="py-2.5 pl-4 align-top">
                      <input
                        type="checkbox"
                        className="size-4"
                        aria-label={t("hiring.compliance.selectTutor", { name: row.name })}
                        checked={selected.includes(row.tutor)}
                        onChange={() => toggle(row.tutor)}
                      />
                    </td>
                  ) : null}
                  <th
                    scope="row"
                    className="px-4 py-2.5 text-left align-top font-medium whitespace-nowrap"
                  >
                    <Link
                      to="/tutors/$tutorId"
                      params={{ tutorId: row.tutor }}
                      className="underline-offset-2 hover:underline"
                    >
                      {row.name}
                    </Link>
                    {row.status === "restricted" ? (
                      <span className="block text-xs font-normal text-muted-foreground">
                        {t("recruitment.restricted")}
                      </span>
                    ) : null}
                  </th>
                  {board.data.requirements.map((r) => {
                    const cell = row.cells[r.key];
                    const status = cell?.status ?? "missing";
                    return (
                      <td key={r.key} className="px-4 py-2.5 align-top whitespace-nowrap">
                        <span className={CELL_TONE[status] ?? ""}>
                          {t(`recruitment.cell.${status}`)}
                        </span>
                        {cell?.expiry_date ? (
                          <span className="block text-xs text-muted-foreground tabular-nums">
                            {formatDate(cell.expiry_date)}
                          </span>
                        ) : null}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
          {!board.data.rows.length ? (
            <p className="px-5 py-10 text-center text-sm text-muted-foreground">
              {t("hiring.compliance.noRows")}
            </p>
          ) : null}
        </div>
      )}
    </Page>
  );
}

/** Compliance records on the tutor record, with verify and reject (FR-18-6). */
export function TutorComplianceCard({ tutorId }: { tutorId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canView = usePermission("compliance.view");
  const canVerify = usePermission("compliance.verify");
  const data = useQuery({
    queryKey: ["tutor-compliance", tutorId],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/tutors/{id}/compliance", { params: { path: { id: tutorId } } }),
      ),
    enabled: canView,
  });
  const decide = useMutation({
    mutationFn: async ({ id, ok }: { id: string; ok: boolean }) =>
      ok
        ? unwrap(
            await api.POST("/api/v1/compliance/records/{id}/verify", { params: { path: { id } } }),
          )
        : unwrap(
            await api.POST("/api/v1/compliance/records/{id}/reject", {
              params: { path: { id } },
              body: { reason: t("recruitment.defaultRejectReason") },
            }),
          ),
    onSuccess: () =>
      void queryClient.invalidateQueries({ queryKey: ["tutor-compliance", tutorId] }),
  });
  if (!canView || !data.data) return null;
  const records = new Map(data.data.records.map((r) => [r.requirement, r]));
  return (
    <Panel
      title={t("recruitment.compliance")}
      aside={
        data.data.restricted ? (
          <span className="font-semibold text-margin">{t("recruitment.restricted")}</span>
        ) : null
      }
      flush
    >
      <PanelRows>
        {data.data.requirements.map((req) => {
          const record = records.get(req.id);
          const status =
            record && !record.valid && record.status === "verified"
              ? "expired"
              : (record?.status ?? "missing");
          return (
            <PanelRow key={req.id}>
              <NamePlate
                name={req.name}
                context={
                  <>
                    <span className={CELL_TONE[status] ?? ""}>
                      {t(`recruitment.cell.${status}`)}
                    </span>
                    {record?.expiry_date ? (
                      <span className="tabular-nums"> · {formatDate(record.expiry_date)}</span>
                    ) : null}
                  </>
                }
                aside={
                  canVerify && record?.status === "submitted" ? (
                    <>
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => decide.mutate({ id: record.id, ok: true })}
                      >
                        {t("recruitment.verify")}
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="text-muted-foreground"
                        onClick={() => decide.mutate({ id: record.id, ok: false })}
                      >
                        {t("recruitment.reject")}
                      </Button>
                    </>
                  ) : null
                }
              />
            </PanelRow>
          );
        })}
      </PanelRows>
      {decide.error ? (
        <div className="px-5 pb-4">
          <Alert tone="danger">{decide.error.message}</Alert>
        </div>
      ) : null}
    </Panel>
  );
}

// --- public pages ---------------------------------------------------------------------------

/** Open roles at ``/vacancies`` and the application form at ``/vacancies/<slug>`` (FR-18-1). */
export function VacanciesPage() {
  const { t } = useTranslation();
  const openings = useQuery({
    queryKey: ["public-openings"],
    queryFn: async () => unwrap(await api.GET("/api/v1/public/job-openings")),
  });
  return (
    <PublicLayout title={t("recruitment.jobsTitle")}>
      {openings.isPending ? <Spinner label={t("grid.loading")} /> : null}
      {openings.data && !openings.data.length ? (
        <p className="text-sm text-muted-foreground">{t("recruitment.noOpenings")}</p>
      ) : null}
      {openings.data?.length ? (
        <Panel label={t("recruitment.jobsTitle")} flush>
          <PanelRows>
            {openings.data.map((o) => (
              <PanelRow key={o.slug} className="hover:bg-muted/60">
                <NamePlate
                  name={
                    <a className="underline-offset-2 hover:underline" href={`/vacancies/${o.slug}`}>
                      {o.title}
                    </a>
                  }
                  context={o.location || undefined}
                />
              </PanelRow>
            ))}
          </PanelRows>
        </Panel>
      ) : null}
    </PublicLayout>
  );
}

export function VacancyPage({ slug }: { slug: string }) {
  const { t } = useTranslation();
  const [answers, setAnswers] = useState<Record<string, unknown>>({});
  const [token, setToken] = useState("");
  const opening = useQuery({
    queryKey: ["public-opening", slug],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/public/job-openings/{slug}", { params: { path: { slug } } })),
    retry: false,
  });
  const apply = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/public/job-openings/{slug}", {
          params: { path: { slug } },
          body: {
            data: answers as Record<string, never>,
            captcha_token: token,
            website: "",
            // E25: a tutor's referral code from the shared link (?ref=CODE).
            ref: new URLSearchParams(window.location.search).get("ref") ?? "",
          },
        }),
      ),
  });
  if (opening.isError)
    return (
      <PublicLayout title={t("recruitment.noOpening")}>
        <a className="text-sm text-link underline-offset-2 hover:underline" href="/vacancies">
          {t("designS8.recruitment.allVacancies")}
        </a>
      </PublicLayout>
    );
  if (!opening.data) return <Spinner label={t("grid.loading")} />;
  const schema = opening.data.schema as unknown as Schema;
  const errors = (apply.error as { problem?: { errors?: Record<string, string[]> } } | null)
    ?.problem?.errors;
  return (
    <PublicLayout title={opening.data.title}>
      {opening.data.description ? (
        <p className="mb-6 whitespace-pre-line">{opening.data.description}</p>
      ) : null}
      {apply.isSuccess ? (
        <p role="status">{t("recruitment.applied")}</p>
      ) : (
        <form
          className="space-y-6"
          onSubmit={(e) => {
            e.preventDefault();
            apply.mutate();
          }}
        >
          {schema.steps.map((step, s) => (
            <fieldset key={s} className="space-y-3">
              {step.title ? (
                <legend className="mb-1 text-base font-semibold">{step.title}</legend>
              ) : null}
              {step.fields.map((f) => (
                <PublicField
                  key={f.key}
                  field={f}
                  value={answers[f.key]}
                  error={errors?.[f.key]?.[0]}
                  onChange={(v) => setAnswers({ ...answers, [f.key]: v })}
                  uploadTarget={{ target: "opening", slug }}
                />
              ))}
            </fieldset>
          ))}
          {opening.data.turnstile_site_key ? (
            <Turnstile siteKey={opening.data.turnstile_site_key} onToken={setToken} />
          ) : null}
          {apply.error && !errors ? <Alert tone="danger">{apply.error.message}</Alert> : null}
          <Button type="submit" className="w-full sm:w-auto" loading={apply.isPending}>
            {t("recruitment.apply")}
          </Button>
        </form>
      )}
    </PublicLayout>
  );
}

/** The applicant picks an interview time at ``/interviews/<token>``. */
export function InterviewChoicePage({ token }: { token: string }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const interview = useQuery({
    queryKey: ["interview", token],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/public/interviews/{token}", { params: { path: { token } } })),
    retry: false,
  });
  const book = useMutation({
    mutationFn: async (start: string) =>
      unwrap(
        await api.POST("/api/v1/public/interviews/{token}", {
          params: { path: { token } },
          body: { start },
        }),
      ),
    onSuccess: (data) => queryClient.setQueryData(["interview", token], data),
  });
  if (interview.isError)
    return (
      <PublicLayout title={t("recruitment.linkExpired")}>
        <p className="text-sm text-muted-foreground">{t("designS8.recruitment.askAgain")}</p>
      </PublicLayout>
    );
  if (!interview.data) return <Spinner label={t("grid.loading")} />;
  const i = interview.data;
  const timeOf = (iso: string) =>
    formatDateTime(iso, i18n.language, undefined, { timeStyle: "short" });
  return (
    <PublicLayout title={t("recruitment.chooseTime", { organisation: i.organisation })}>
      {i.status === "booked" && i.start ? (
        <div role="status" className="space-y-2">
          <p>{t("recruitment.interviewBooked", { when: formatDateTime(i.start) })}</p>
          {i.meeting_url ? (
            <p>
              <a
                className="text-link underline-offset-2 hover:underline"
                href={i.meeting_url}
                target="_blank"
                rel="noreferrer"
              >
                {t("hiring.interviews.joinCall")}
              </a>
            </p>
          ) : (
            <p className="text-muted-foreground">{t("hiring.interviews.linkToFollow")}</p>
          )}
        </div>
      ) : !i.options.length ? (
        <p>{t("hiring.interviews.noTimes")}</p>
      ) : (
        <div className="space-y-4">
          {Object.entries(
            i.options.reduce<Record<string, string[]>>((days, option) => {
              const day = formatDate(option);
              (days[day] ??= []).push(option);
              return days;
            }, {}),
          ).map(([day, options]) => (
            <Panel key={day} title={day}>
              <ul className="flex flex-wrap gap-2">
                {options.map((option) => (
                  <li key={option}>
                    <Button
                      variant="secondary"
                      className="tabular-nums"
                      aria-label={formatDateTime(option)}
                      loading={book.isPending && book.variables === option}
                      onClick={() => book.mutate(option)}
                    >
                      {timeOf(option)}
                    </Button>
                  </li>
                ))}
              </ul>
            </Panel>
          ))}
        </div>
      )}
      {book.error ? (
        <Alert tone="danger" className="mt-4">
          {book.error.message}
        </Alert>
      ) : null}
    </PublicLayout>
  );
}

/** A referee gives a reference at ``/references/<token>`` (FR-18-4). */
export function ReferencePage({ token }: { token: string }) {
  const { t } = useTranslation();
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [rating, setRating] = useState("4");
  const [concerns, setConcerns] = useState(false);
  const reference = useQuery({
    queryKey: ["reference", token],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/public/references/{token}", { params: { path: { token } } })),
    retry: false,
  });
  const give = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/public/references/{token}", {
          params: { path: { token } },
          body: { responses: answers, rating: Number(rating), concerns },
        }),
      ),
  });
  if (reference.isError)
    return (
      <PublicLayout title={t("recruitment.linkExpired")}>
        <p className="text-sm text-muted-foreground">{t("designS8.recruitment.askAgain")}</p>
      </PublicLayout>
    );
  if (!reference.data) return <Spinner label={t("grid.loading")} />;
  const r = reference.data;
  if (give.isSuccess || r.status !== "requested") {
    return (
      <PublicLayout title={t("recruitment.referenceFor", { name: r.applicant })}>
        <p role="status">{t("recruitment.referenceThanks")}</p>
      </PublicLayout>
    );
  }
  return (
    <PublicLayout title={t("recruitment.referenceFor", { name: r.applicant })}>
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          give.mutate();
        }}
      >
        {r.questions.map((q, i) => (
          <label key={q} className="flex flex-col gap-1 text-sm">
            <span className="font-medium">{q}</span>
            <textarea
              className="rounded-md border border-field bg-surface px-3 py-2 text-sm"
              rows={3}
              value={answers[`q${i + 1}`] ?? ""}
              onChange={(e) => setAnswers({ ...answers, [`q${i + 1}`]: e.target.value })}
            />
          </label>
        ))}
        <SelectField
          label={t("recruitment.overallRating")}
          className="w-24 tabular-nums"
          value={rating}
          onChange={(e) => setRating(e.target.value)}
          options={["5", "4", "3", "2", "1"].map((n) => ({ value: n, label: n }))}
        />
        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            className="mt-0.5 size-4"
            checked={concerns}
            onChange={(e) => setConcerns(e.target.checked)}
          />
          {t("recruitment.raiseConcern")}
        </label>
        {give.error ? <Alert tone="danger">{give.error.message}</Alert> : null}
        <Button type="submit" className="w-full sm:w-auto" loading={give.isPending}>
          {t("recruitment.sendReference")}
        </Button>
      </form>
    </PublicLayout>
  );
}
