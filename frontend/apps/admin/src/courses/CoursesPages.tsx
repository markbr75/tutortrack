import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatDateTime, formatMoney, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, Tabs, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState, type FormEvent, type ReactNode } from "react";

import { api, useOrganisation, usePermission } from "../api";
import { PublicLayout } from "../layout/PublicLayout";

type GroupClass = components["schemas"]["GroupClass"];
type Course = components["schemas"]["Course"];
type Term = components["schemas"]["Term"];
type RosterRow = components["schemas"]["RosterRow"];
type RegisterRow = components["schemas"]["RegisterRow"];
type Outcome = RegisterRow["outcome"];

const PAGE = { page_size: 200 };
const WEEKDAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"] as const;
const PRICING = ["per_term", "per_month", "per_session", "full_course", "instalments"] as const;
const OUTCOMES: Outcome[] = [
  "present",
  "late",
  "absent_notified",
  "no_show",
  "cancelled_client",
  "cancelled_tutor",
  "cancelled_admin",
];

function Table({
  caption,
  headers,
  children,
}: {
  caption: string;
  headers: string[];
  children: ReactNode;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <caption className="mb-2 text-left font-semibold">{caption}</caption>
        <thead>
          <tr className="text-left">
            {headers.map((h) => (
              <th key={h} scope="col" className="px-2 py-1">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

function Cell({ children }: { children: ReactNode }) {
  return <td className="border-t border-border px-2 py-1 align-top">{children}</td>;
}

function FormCard({
  title,
  submit,
  pending,
  error,
  onSubmit,
  children,
}: {
  title: string;
  submit: string;
  pending?: boolean;
  error?: Error | null;
  onSubmit: () => void;
  children: ReactNode;
}) {
  return (
    <form
      className="space-y-3 rounded-md border border-border p-4"
      aria-label={title}
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        onSubmit();
      }}
    >
      <h2 className="font-semibold">{title}</h2>
      <div className="grid gap-3 sm:grid-cols-2">{children}</div>
      {error ? <Alert tone="danger">{error.message}</Alert> : null}
      <Button type="submit" disabled={pending}>
        {submit}
      </Button>
    </form>
  );
}

function weekdayNames(days: number[], locale: string): string {
  const monday = new Date(Date.UTC(2024, 0, 1));
  return days
    .map((d) =>
      new Date(monday.getTime() + d * 86_400_000).toLocaleDateString(locale, {
        weekday: "short",
        timeZone: "UTC",
      }),
    )
    .join(", ");
}

const TABS = ["classes", "courses", "terms", "rollover"] as const;
type Tab = (typeof TABS)[number];

/** Courses, classes, terms and re-enrolment (E20-T10). */
export function CoursesPage() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>("classes");
  return (
    <section>
      <h1 className="mb-4 text-2xl font-semibold">{t("courses.title")}</h1>
      <Tabs
        label={t("courses.title")}
        tabs={TABS.map((key) => ({ key, label: t(`courses.tabs.${key}`) }))}
        value={tab}
        onChange={setTab}
      >
        {tab === "classes" ? <ClassesSection /> : null}
        {tab === "courses" ? <CoursesSection /> : null}
        {tab === "terms" ? <TermsSection /> : null}
        {tab === "rollover" ? <RolloverSection /> : null}
      </Tabs>
    </section>
  );
}

function useTerms() {
  return useQuery({
    queryKey: ["courses", "terms"],
    queryFn: async () => unwrap(await api.GET("/api/v1/terms", { params: { query: PAGE } })),
  });
}

function useCourses() {
  return useQuery({
    queryKey: ["courses", "courses"],
    queryFn: async () => unwrap(await api.GET("/api/v1/courses", { params: { query: PAGE } })),
  });
}

function ClassesSection() {
  const { t, i18n } = useTranslation();
  const canManage = usePermission("courses.manage");
  const [term, setTerm] = useState("");
  const terms = useTerms();
  const classes = useQuery({
    queryKey: ["courses", "classes", term],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/classes", {
          params: { query: { ...PAGE, ...(term ? { term } : {}) } },
        }),
      ),
  });
  return (
    <div className="space-y-6">
      <SelectField
        label={t("courses.term")}
        value={term}
        onChange={(e) => setTerm(e.target.value)}
        options={[
          { value: "", label: t("courses.allTerms") },
          ...(terms.data?.results ?? []).map((x) => ({ value: x.id, label: x.name })),
        ]}
      />
      {classes.isLoading ? <Spinner className="size-5" label={t("grid.loading")} /> : null}
      {classes.data && !classes.data.results.length ? (
        <p className="text-sm">{t("courses.noClasses")}</p>
      ) : null}
      {classes.data?.results.length ? (
        <Table
          caption={t("courses.tabs.classes")}
          headers={[
            t("courses.class"),
            t("courses.course"),
            t("courses.when"),
            t("courses.places"),
            t("courses.statusLabel"),
          ]}
        >
          {classes.data.results.map((c) => (
            <tr key={c.id}>
              <Cell>
                <Link to="/classes/$classId" params={{ classId: c.id }} className="underline">
                  {c.name}
                </Link>
              </Cell>
              <Cell>{c.course_name}</Cell>
              <Cell>
                {weekdayNames(c.weekdays, i18n.language)} {c.start_time.slice(0, 5)} · {c.term_name}
              </Cell>
              <Cell>
                {t("courses.placesTaken", { enrolled: c.enrolled, capacity: c.capacity })}
                {c.waiting ? ` · ${t("courses.waitingCount", { count: c.waiting })}` : ""}
              </Cell>
              <Cell>{t(`courses.status.${c.status}`)}</Cell>
            </tr>
          ))}
        </Table>
      ) : null}
      {canManage ? <NewClassForm /> : null}
    </div>
  );
}

function NewClassForm() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const terms = useTerms();
  const courses = useCourses();
  const tutors = useQuery({
    queryKey: ["tutors", "active"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/tutors", {
          params: { query: { status: ["active"], page_size: 200 } },
        }),
      ),
  });
  const empty = {
    course: "",
    term: "",
    name: "",
    day: "SA",
    start_time: "10:00",
    duration: "60",
    capacity: "",
    tutor: "",
  };
  const [draft, setDraft] = useState(empty);
  const [skipped, setSkipped] = useState<string[]>([]);
  const create = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/classes", {
          body: {
            course: draft.course,
            term: draft.term,
            name: draft.name,
            start_time: draft.start_time,
            duration_minutes: Number(draft.duration),
            rrule: `FREQ=WEEKLY;BYDAY=${draft.day}`,
            ...(draft.capacity ? { capacity: Number(draft.capacity) } : {}),
            teachers: draft.tutor ? [{ tutor: draft.tutor, role: "lead" as const }] : [],
            status: "open",
            conflict_mode: "skip",
          },
        }),
      ),
    onSuccess: (data) => {
      setSkipped(data.skipped_dates);
      setDraft(empty);
      void queryClient.invalidateQueries({ queryKey: ["courses"] });
    },
  });
  return (
    <>
      <FormCard
        title={t("courses.newClass")}
        submit={t("courses.createClass")}
        pending={create.isPending}
        error={create.error}
        onSubmit={() => create.mutate()}
      >
        <SelectField
          label={t("courses.course")}
          value={draft.course}
          required
          onChange={(e) => setDraft({ ...draft, course: e.target.value })}
          options={[
            { value: "", label: "–" },
            ...(courses.data?.results ?? []).map((c) => ({ value: c.id, label: c.name })),
          ]}
        />
        <SelectField
          label={t("courses.term")}
          value={draft.term}
          required
          onChange={(e) => setDraft({ ...draft, term: e.target.value })}
          options={[
            { value: "", label: "–" },
            ...(terms.data?.results ?? []).map((x) => ({ value: x.id, label: x.name })),
          ]}
        />
        <TextField
          label={t("courses.className")}
          value={draft.name}
          required
          onChange={(e) => setDraft({ ...draft, name: e.target.value })}
        />
        <SelectField
          label={t("courses.day")}
          value={draft.day}
          onChange={(e) => setDraft({ ...draft, day: e.target.value })}
          options={WEEKDAYS.map((d) => ({ value: d, label: t(`courses.weekdays.${d}`) }))}
        />
        <TextField
          label={t("courses.startTime")}
          type="time"
          value={draft.start_time}
          required
          onChange={(e) => setDraft({ ...draft, start_time: e.target.value })}
        />
        <TextField
          label={t("courses.duration")}
          type="number"
          min={5}
          value={draft.duration}
          onChange={(e) => setDraft({ ...draft, duration: e.target.value })}
        />
        <TextField
          label={t("courses.capacity")}
          type="number"
          min={1}
          hint={t("courses.capacityHint")}
          value={draft.capacity}
          onChange={(e) => setDraft({ ...draft, capacity: e.target.value })}
        />
        <SelectField
          label={t("courses.teacher")}
          value={draft.tutor}
          onChange={(e) => setDraft({ ...draft, tutor: e.target.value })}
          options={[
            { value: "", label: "–" },
            ...(tutors.data?.results ?? []).map((x) => ({ value: x.id, label: x.full_name })),
          ]}
        />
      </FormCard>
      {skipped.length ? (
        <Alert tone="warning">
          {t("courses.skipped", { dates: skipped.map((d) => formatDate(d)).join(", ") })}
        </Alert>
      ) : null}
    </>
  );
}

function CoursesSection() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const canManage = usePermission("courses.manage");
  const { data: org } = useOrganisation();
  const courses = useCourses();
  const services = useQuery({
    queryKey: ["catalogue", "services"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/catalogue/services", { params: { query: PAGE } })),
    enabled: canManage,
  });
  const empty = {
    name: "",
    service: "",
    pricing_model: "per_term",
    price: "",
    registration_fee: "",
    instalments: "3",
    public_description: "",
    is_public: true,
  };
  const [draft, setDraft] = useState(empty);
  const currency =
    services.data?.results.find((s) => s.id === draft.service)?.currency ??
    org?.default_currency ??
    "GBP";
  const create = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/courses", {
          body: {
            name: draft.name,
            service: draft.service,
            pricing_model: draft.pricing_model as (typeof PRICING)[number],
            price: { amount: draft.price, currency },
            registration_fee: draft.registration_fee
              ? { amount: draft.registration_fee, currency }
              : null,
            instalments: draft.pricing_model === "instalments" ? Number(draft.instalments) : 1,
            public_description: draft.public_description,
            is_public: draft.is_public,
          },
        }),
      ),
    onSuccess: () => {
      setDraft(empty);
      void queryClient.invalidateQueries({ queryKey: ["courses"] });
    },
  });
  return (
    <div className="space-y-6">
      {courses.data && !courses.data.results.length ? (
        <p className="text-sm">{t("courses.noCourses")}</p>
      ) : null}
      {courses.data?.results.length ? (
        <Table
          caption={t("courses.tabs.courses")}
          headers={[
            t("courses.name"),
            t("courses.pricing"),
            t("courses.price"),
            t("courses.public"),
            t("courses.tabs.classes"),
          ]}
        >
          {courses.data.results.map((c: Course) => (
            <tr key={c.id}>
              <Cell>{c.name}</Cell>
              <Cell>{t(`courses.pricingModels.${c.pricing_model}`)}</Cell>
              <Cell>{formatMoney(c.price, i18n.language)}</Cell>
              <Cell>{c.is_public ? t("courses.yes") : t("courses.no")}</Cell>
              <Cell>{c.classes_count}</Cell>
            </tr>
          ))}
        </Table>
      ) : null}
      {canManage ? (
        <FormCard
          title={t("courses.newCourse")}
          submit={t("courses.createCourse")}
          pending={create.isPending}
          error={create.error}
          onSubmit={() => create.mutate()}
        >
          <TextField
            label={t("courses.name")}
            value={draft.name}
            required
            onChange={(e) => setDraft({ ...draft, name: e.target.value })}
          />
          <SelectField
            label={t("courses.service")}
            hint={t("courses.serviceHint")}
            value={draft.service}
            required
            onChange={(e) => setDraft({ ...draft, service: e.target.value })}
            options={[
              { value: "", label: "–" },
              ...(services.data?.results ?? [])
                .filter((s) => s.format !== "one_to_one")
                .map((s) => ({ value: s.id, label: s.name })),
            ]}
          />
          <SelectField
            label={t("courses.pricing")}
            value={draft.pricing_model}
            onChange={(e) => setDraft({ ...draft, pricing_model: e.target.value })}
            options={PRICING.map((p) => ({ value: p, label: t(`courses.pricingModels.${p}`) }))}
          />
          <TextField
            label={t("courses.priceIn", { currency })}
            inputMode="decimal"
            value={draft.price}
            required
            onChange={(e) => setDraft({ ...draft, price: e.target.value })}
          />
          {draft.pricing_model === "instalments" ? (
            <TextField
              label={t("courses.instalments")}
              type="number"
              min={2}
              value={draft.instalments}
              onChange={(e) => setDraft({ ...draft, instalments: e.target.value })}
            />
          ) : null}
          <TextField
            label={t("courses.registrationFee")}
            inputMode="decimal"
            value={draft.registration_fee}
            onChange={(e) => setDraft({ ...draft, registration_fee: e.target.value })}
          />
          <TextField
            label={t("courses.publicDescription")}
            value={draft.public_description}
            onChange={(e) => setDraft({ ...draft, public_description: e.target.value })}
          />
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={draft.is_public}
              onChange={(e) => setDraft({ ...draft, is_public: e.target.checked })}
            />
            {t("courses.showOnWebsite")}
          </label>
        </FormCard>
      ) : null}
    </div>
  );
}

function TermsSection() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canManage = usePermission("courses.manage");
  const terms = useTerms();
  const years = useQuery({
    queryKey: ["courses", "years"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/academic-years", { params: { query: PAGE } })),
  });
  const [year, setYear] = useState({ name: "", start_date: "", end_date: "" });
  const emptyTerm = {
    academic_year: "",
    name: "",
    start_date: "",
    end_date: "",
    break_name: "",
    break_start: "",
    break_end: "",
  };
  const [term, setTerm] = useState(emptyTerm);
  const done = () => void queryClient.invalidateQueries({ queryKey: ["courses"] });
  const addYear = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/academic-years", { body: year })),
    onSuccess: () => {
      setYear({ name: "", start_date: "", end_date: "" });
      done();
    },
  });
  const addTerm = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/terms", {
          body: {
            academic_year: term.academic_year,
            name: term.name,
            start_date: term.start_date,
            end_date: term.end_date,
            breaks:
              term.break_start && term.break_end
                ? [
                    {
                      name: term.break_name || t("courses.halfTerm"),
                      start_date: term.break_start,
                      end_date: term.break_end,
                    },
                  ]
                : [],
          },
        }),
      ),
    onSuccess: () => {
      setTerm(emptyTerm);
      done();
    },
  });
  return (
    <div className="space-y-6">
      {terms.data?.results.length ? (
        <Table
          caption={t("courses.tabs.terms")}
          headers={[t("courses.name"), t("courses.year"), t("courses.dates"), t("courses.breaks")]}
        >
          {terms.data.results.map((x: Term) => (
            <tr key={x.id}>
              <Cell>{x.name}</Cell>
              <Cell>{x.academic_year_name}</Cell>
              <Cell>
                {formatDate(x.start_date)} – {formatDate(x.end_date)}
              </Cell>
              <Cell>
                {(x.breaks ?? [])
                  .map((b) => `${b.name} (${formatDate(b.start_date)} – ${formatDate(b.end_date)})`)
                  .join("; ") || "–"}
              </Cell>
            </tr>
          ))}
        </Table>
      ) : (
        <p className="text-sm">{t("courses.noTerms")}</p>
      )}
      {canManage ? (
        <>
          <FormCard
            title={t("courses.newYear")}
            submit={t("courses.addYear")}
            pending={addYear.isPending}
            error={addYear.error}
            onSubmit={() => addYear.mutate()}
          >
            <TextField
              label={t("courses.name")}
              value={year.name}
              required
              onChange={(e) => setYear({ ...year, name: e.target.value })}
            />
            <TextField
              label={t("courses.starts")}
              type="date"
              value={year.start_date}
              required
              onChange={(e) => setYear({ ...year, start_date: e.target.value })}
            />
            <TextField
              label={t("courses.ends")}
              type="date"
              value={year.end_date}
              required
              onChange={(e) => setYear({ ...year, end_date: e.target.value })}
            />
          </FormCard>
          <FormCard
            title={t("courses.newTerm")}
            submit={t("courses.addTerm")}
            pending={addTerm.isPending}
            error={addTerm.error}
            onSubmit={() => addTerm.mutate()}
          >
            <SelectField
              label={t("courses.year")}
              value={term.academic_year}
              required
              onChange={(e) => setTerm({ ...term, academic_year: e.target.value })}
              options={[
                { value: "", label: "–" },
                ...(years.data?.results ?? []).map((y) => ({ value: y.id, label: y.name })),
              ]}
            />
            <TextField
              label={t("courses.name")}
              value={term.name}
              required
              onChange={(e) => setTerm({ ...term, name: e.target.value })}
            />
            <TextField
              label={t("courses.starts")}
              type="date"
              value={term.start_date}
              required
              onChange={(e) => setTerm({ ...term, start_date: e.target.value })}
            />
            <TextField
              label={t("courses.ends")}
              type="date"
              value={term.end_date}
              required
              onChange={(e) => setTerm({ ...term, end_date: e.target.value })}
            />
            <TextField
              label={t("courses.breakName")}
              value={term.break_name}
              onChange={(e) => setTerm({ ...term, break_name: e.target.value })}
            />
            <TextField
              label={t("courses.breakStarts")}
              type="date"
              value={term.break_start}
              onChange={(e) => setTerm({ ...term, break_start: e.target.value })}
            />
            <TextField
              label={t("courses.breakEnds")}
              type="date"
              value={term.break_end}
              onChange={(e) => setTerm({ ...term, break_end: e.target.value })}
            />
          </FormCard>
        </>
      ) : null}
    </div>
  );
}

function RolloverSection() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canRun = usePermission("courses.rollover.manage");
  const terms = useTerms();
  const rollovers = useQuery({
    queryKey: ["courses", "rollovers"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/enrolments/rollover", { params: { query: PAGE } })),
  });
  const empty = { from_term: "", to_term: "", mode: "confirm", deadline: "" };
  const [draft, setDraft] = useState(empty);
  const done = () => void queryClient.invalidateQueries({ queryKey: ["courses", "rollovers"] });
  const start = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/enrolments/rollover", {
          body: {
            from_term: draft.from_term,
            to_term: draft.to_term,
            mode: draft.mode as "confirm" | "opt_out",
            deadline: new Date(draft.deadline).toISOString(),
          },
        }),
      ),
    onSuccess: () => {
      setDraft(empty);
      done();
    },
  });
  const act = useMutation({
    mutationFn: async ({ id, action }: { id: string; action: "finalise" | "cancel" }) =>
      action === "finalise"
        ? unwrap(
            await api.POST("/api/v1/enrolments/rollover/{id}/finalise", {
              params: { path: { id } },
            }),
          )
        : unwrap(
            await api.POST("/api/v1/enrolments/rollover/{id}/cancel", {
              params: { path: { id } },
            }),
          ),
    onSuccess: done,
  });
  const termOptions = [
    { value: "", label: "–" },
    ...(terms.data?.results ?? []).map((x) => ({ value: x.id, label: x.name })),
  ];
  return (
    <div className="space-y-6">
      <p className="text-sm text-muted-foreground">{t("courses.rolloverHelp")}</p>
      {rollovers.data?.results.length ? (
        <Table
          caption={t("courses.tabs.rollover")}
          headers={[
            t("courses.fromTo"),
            t("courses.deadline"),
            t("courses.statusLabel"),
            t("courses.answers"),
            "",
          ]}
        >
          {rollovers.data.results.map((r) => (
            <tr key={r.id}>
              <Cell>
                {r.from_term_name} → {r.to_term_name}
              </Cell>
              <Cell>{formatDateTime(r.deadline)}</Cell>
              <Cell>{t(`courses.rolloverStatus.${r.status}`)}</Cell>
              <Cell>
                {Object.entries(r.counts)
                  .map(([k, n]) => `${t(`courses.offerStatus.${k}`)}: ${n}`)
                  .join(", ")}
              </Cell>
              <Cell>
                {canRun && r.status === "running" ? (
                  <span className="flex gap-2">
                    <Button size="sm" onClick={() => act.mutate({ id: r.id, action: "finalise" })}>
                      {t("courses.finishNow")}
                    </Button>
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => act.mutate({ id: r.id, action: "cancel" })}
                    >
                      {t("courses.cancel")}
                    </Button>
                  </span>
                ) : null}
              </Cell>
            </tr>
          ))}
        </Table>
      ) : null}
      {act.error ? <Alert tone="danger">{act.error.message}</Alert> : null}
      {canRun ? (
        <FormCard
          title={t("courses.startRollover")}
          submit={t("courses.start")}
          pending={start.isPending}
          error={start.error}
          onSubmit={() => start.mutate()}
        >
          <SelectField
            label={t("courses.fromTerm")}
            value={draft.from_term}
            required
            onChange={(e) => setDraft({ ...draft, from_term: e.target.value })}
            options={termOptions}
          />
          <SelectField
            label={t("courses.toTerm")}
            value={draft.to_term}
            required
            onChange={(e) => setDraft({ ...draft, to_term: e.target.value })}
            options={termOptions}
          />
          <SelectField
            label={t("courses.mode")}
            value={draft.mode}
            onChange={(e) => setDraft({ ...draft, mode: e.target.value })}
            options={["confirm", "opt_out"].map((m) => ({
              value: m,
              label: t(`courses.modes.${m}`),
            }))}
          />
          <TextField
            label={t("courses.deadline")}
            type="datetime-local"
            value={draft.deadline}
            required
            onChange={(e) => setDraft({ ...draft, deadline: e.target.value })}
          />
        </FormCard>
      ) : null}
    </div>
  );
}

// --- one class --------------------------------------------------------------------------------

/** A class: places, roster (withdraw, transfer), enrolment, sessions and waitlist. */
export function ClassPage({ classId }: { classId: string }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const canManage = usePermission("courses.manage");
  const canEnrol = usePermission("courses.enrolment.manage");
  const detail = useQuery({
    queryKey: ["courses", "class", classId],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/classes/{id}", { params: { path: { id: classId } } })),
  });
  const roster = useQuery({
    queryKey: ["courses", "class", classId, "roster"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/classes/{id}/roster", { params: { path: { id: classId } } })),
  });
  const sessions = useQuery({
    queryKey: ["courses", "class", classId, "sessions"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/classes/{id}/sessions", { params: { path: { id: classId } } })),
  });
  const waitlist = useQuery({
    queryKey: ["courses", "class", classId, "waitlist"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/classes/{id}/waitlist", { params: { path: { id: classId } } })),
  });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["courses"] });
  const lifecycle = useMutation({
    mutationFn: async (action: "open" | "cancel") =>
      action === "open"
        ? unwrap(await api.POST("/api/v1/classes/{id}/open", { params: { path: { id: classId } } }))
        : unwrap(
            await api.POST("/api/v1/classes/{id}/cancel", {
              params: { path: { id: classId } },
              body: { reason: "" },
            }),
          ),
    onSuccess: refresh,
  });
  if (detail.isLoading) return <Spinner className="m-8 size-6" label={t("grid.loading")} />;
  if (!detail.data) return <Alert tone="danger">{t("courses.notFound")}</Alert>;
  const c: GroupClass = detail.data;
  const active = (roster.data ?? []).filter((r) =>
    ["enrolled", "trial", "pending_payment"].includes(r.status),
  );
  return (
    <section className="space-y-6">
      <header>
        <p className="text-sm text-muted-foreground">
          <Link to="/courses" className="underline">
            {t("courses.title")}
          </Link>{" "}
          / {c.course_name}
        </p>
        <h1 className="text-2xl font-semibold">{c.name}</h1>
        <p className="text-sm">
          {weekdayNames(c.weekdays, i18n.language)} {c.start_time.slice(0, 5)} · {c.term_name} ·{" "}
          {formatDate(c.start_date)} – {formatDate(c.end_date)}
          {c.room_name ? ` · ${c.room_name}` : c.location_name ? ` · ${c.location_name}` : ""}
        </p>
        <p className="mt-1 text-sm" role="status">
          {t(`courses.status.${c.status}`)} · {t("courses.placesLeft", { count: c.places_left })} ·{" "}
          {t("courses.placesTaken", { enrolled: c.enrolled, capacity: c.capacity })}
        </p>
        {canManage ? (
          <div className="mt-2 flex gap-2">
            {c.status === "draft" ? (
              <Button size="sm" onClick={() => lifecycle.mutate("open")}>
                {t("courses.openClass")}
              </Button>
            ) : null}
            {!["cancelled", "completed"].includes(c.status) ? (
              <Button size="sm" variant="secondary" onClick={() => lifecycle.mutate("cancel")}>
                {t("courses.cancelClass")}
              </Button>
            ) : null}
          </div>
        ) : null}
        {lifecycle.error ? <Alert tone="danger">{lifecycle.error.message}</Alert> : null}
      </header>
      <Table
        caption={t("courses.roster")}
        headers={[t("courses.student"), t("courses.statusLabel"), t("courses.dates"), ""]}
      >
        {(roster.data ?? []).map((r) => (
          <RosterLine key={r.enrolment} row={r} classId={classId} canEnrol={canEnrol} />
        ))}
      </Table>
      {roster.data && !active.length ? (
        <p className="text-sm">{t("courses.nobodyEnrolled")}</p>
      ) : null}
      {canEnrol && !["cancelled", "completed"].includes(c.status) ? (
        <EnrolForm groupClass={c} onDone={refresh} />
      ) : null}
      <Table
        caption={t("courses.sessions")}
        headers={[t("courses.number"), t("courses.date"), t("courses.students"), ""]}
      >
        {(sessions.data ?? []).map((s) => (
          <tr key={s.id}>
            <Cell>{s.number}</Cell>
            <Cell>{formatDateTime(s.start)}</Cell>
            <Cell>{s.attendees}</Cell>
            <Cell>
              {s.lesson_status === "cancelled" ? (
                t("courses.cancelled")
              ) : (
                <Link
                  to="/class-sessions/$sessionId/register"
                  params={{ sessionId: s.id }}
                  className="underline"
                >
                  {t("courses.register")}
                </Link>
              )}
            </Cell>
          </tr>
        ))}
      </Table>
      <Table
        caption={t("courses.waitlist")}
        headers={[t("courses.position"), t("courses.student"), t("courses.statusLabel")]}
      >
        {(waitlist.data ?? []).map((w) => (
          <tr key={w.id}>
            <Cell>{w.position ?? "–"}</Cell>
            <Cell>{w.student_name}</Cell>
            <Cell>
              {t(`courses.waitStatus.${w.status}`)}
              {w.offer_expires_at
                ? ` · ${t("courses.offerUntil", { date: formatDateTime(w.offer_expires_at) })}`
                : ""}
            </Cell>
          </tr>
        ))}
      </Table>
    </section>
  );
}

function RosterLine({
  row,
  classId,
  canEnrol,
}: {
  row: RosterRow;
  classId: string;
  canEnrol: boolean;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [moving, setMoving] = useState(false);
  const [target, setTarget] = useState("");
  const others = useQuery({
    queryKey: ["courses", "classes", "transfer-targets"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/classes", {
          params: { query: { ...PAGE, status: ["open", "full", "running"] } },
        }),
      ),
    enabled: moving,
  });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["courses"] });
  const withdraw = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/enrolments/{id}/withdraw", {
          params: { path: { id: row.enrolment } },
          body: { reason: "" },
        }),
      ),
    onSuccess: refresh,
  });
  const transfer = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/enrolments/{id}/transfer", {
          params: { path: { id: row.enrolment } },
          body: { to_class: target, reason: "", override_capacity: false },
        }),
      ),
    onSuccess: () => {
      setMoving(false);
      refresh();
    },
  });
  const attending = ["enrolled", "trial"].includes(row.status);
  return (
    <tr>
      <Cell>
        {row.student_name}
        <span className="block text-xs text-muted-foreground">{row.client_name}</span>
      </Cell>
      <Cell>{t(`courses.enrolmentStatus.${row.status}`)}</Cell>
      <Cell>
        {formatDate(row.start_date)}
        {row.end_date ? ` – ${formatDate(row.end_date)}` : ""}
      </Cell>
      <Cell>
        {canEnrol && attending ? (
          <span className="flex flex-wrap items-end gap-2">
            <Button size="sm" variant="secondary" onClick={() => withdraw.mutate()}>
              {t("courses.withdraw", { student: row.student_name })}
            </Button>
            <Button size="sm" variant="secondary" onClick={() => setMoving(!moving)}>
              {t("courses.transfer")}
            </Button>
            {moving ? (
              <>
                <SelectField
                  label={t("courses.moveTo")}
                  value={target}
                  onChange={(e) => setTarget(e.target.value)}
                  options={[
                    { value: "", label: "–" },
                    ...(others.data?.results ?? [])
                      .filter((x) => x.id !== classId)
                      .map((x) => ({ value: x.id, label: `${x.course_name} – ${x.name}` })),
                  ]}
                />
                <Button size="sm" disabled={!target} onClick={() => transfer.mutate()}>
                  {t("courses.move")}
                </Button>
              </>
            ) : null}
          </span>
        ) : null}
        {withdraw.error ? <Alert tone="danger">{withdraw.error.message}</Alert> : null}
        {transfer.error ? <Alert tone="danger">{transfer.error.message}</Alert> : null}
      </Cell>
    </tr>
  );
}

function EnrolForm({ groupClass, onDone }: { groupClass: GroupClass; onDone: () => void }) {
  const { t, i18n } = useTranslation();
  const [student, setStudent] = useState("");
  const [trial, setTrial] = useState(false);
  const [override, setOverride] = useState(false);
  const students = useQuery({
    queryKey: ["students", "enrollable"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/students", {
          params: { query: { status: ["active", "trial", "waiting", "lead"], page_size: 200 } },
        }),
      ),
  });
  const quote = useQuery({
    queryKey: ["courses", "quote", groupClass.id, student, trial],
    queryFn: async () =>
      unwrap(
        await api.POST("/api/v1/enrolments/quote", {
          body: { group_class: groupClass.id, student, trial },
        }),
      ),
    enabled: Boolean(student),
  });
  const enrol = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/enrolments", {
          body: {
            group_class: groupClass.id,
            student,
            trial,
            override_capacity: override,
            skip_eligibility: false,
          },
        }),
      ),
    onSuccess: () => {
      setStudent("");
      onDone();
    },
  });
  const waitlist = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/classes/{id}/waitlist", {
          params: { path: { id: groupClass.id } },
          body: { student, notes: "" },
        }),
      ),
    onSuccess: () => {
      setStudent("");
      onDone();
    },
  });
  const q = quote.data;
  return (
    <FormCard
      title={t("courses.enrolStudent")}
      submit={t("courses.enrol")}
      pending={enrol.isPending}
      error={enrol.error ?? waitlist.error}
      onSubmit={() => enrol.mutate()}
    >
      <SelectField
        label={t("courses.student")}
        value={student}
        required
        onChange={(e) => setStudent(e.target.value)}
        options={[
          { value: "", label: "–" },
          ...(students.data?.results ?? []).map((s) => ({ value: s.id, label: s.full_name })),
        ]}
      />
      <div className="flex flex-col gap-2 text-sm">
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={trial} onChange={(e) => setTrial(e.target.checked)} />
          {t("courses.trial")}
        </label>
        {groupClass.places_left <= 0 ? (
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={override}
              onChange={(e) => setOverride(e.target.checked)}
            />
            {t("courses.overrideCapacity")}
          </label>
        ) : null}
      </div>
      {q ? (
        <div className="sm:col-span-2 rounded-md bg-muted p-3 text-sm" aria-live="polite">
          <p>
            {t("courses.feeDue", { amount: formatMoney(q.fee_due, i18n.language) })}
            {q.units.total && q.units.remaining < q.units.total
              ? ` ${t("courses.prorated", { remaining: q.units.remaining, total: q.units.total })}`
              : ""}
          </p>
          {q.discounts.map((d) => (
            <p key={d.name}>
              {d.name}: {formatMoney(d.amount, i18n.language)}
            </p>
          ))}
          <p>{t("courses.dueNow", { amount: formatMoney(q.due_now, i18n.language) })}</p>
          {q.problems?.length ? <Alert tone="warning">{q.problems.join(" ")}</Alert> : null}
        </div>
      ) : null}
      {groupClass.places_left <= 0 && groupClass.waitlist_enabled ? (
        <Button
          type="button"
          variant="secondary"
          disabled={!student}
          onClick={() => waitlist.mutate()}
        >
          {t("courses.addToWaitlist")}
        </Button>
      ) : null}
    </FormCard>
  );
}

// --- register ---------------------------------------------------------------------------------

/** The class register: everyone at once, with absence reasons (FR-20-6). */
export function RegisterPage({ sessionId }: { sessionId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const register = useQuery({
    queryKey: ["courses", "register", sessionId],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/class-sessions/{id}/register", {
          params: { path: { id: sessionId } },
        }),
      ),
  });
  const session = useQuery({
    queryKey: ["courses", "session", sessionId],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/class-sessions/{id}", { params: { path: { id: sessionId } } })),
  });
  const [rows, setRows] = useState<Record<string, { outcome: Outcome; reason: string }>>({});
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/class-sessions/{id}/register", {
          params: { path: { id: sessionId } },
          body: {
            rows: (register.data?.rows ?? []).map((r) => ({
              student: r.student,
              outcome: rows[r.student]?.outcome ?? r.outcome,
              absence_reason: rows[r.student]?.reason ?? r.absence_reason ?? "",
            })),
          },
        }),
      ),
    onSuccess: (data) => {
      setRows({});
      queryClient.setQueryData(["courses", "register", sessionId], data);
    },
  });
  if (!register.data) return <Spinner className="m-8 size-6" label={t("grid.loading")} />;
  const markAll = () =>
    setRows(
      Object.fromEntries(
        register.data.rows.map((r) => [r.student, { outcome: "present" as Outcome, reason: "" }]),
      ),
    );
  return (
    <section className="space-y-4">
      <h1 className="text-2xl font-semibold">
        {t("courses.registerFor", {
          name: session.data ? `${session.data.course_name} – ${session.data.class_name}` : "",
        })}
      </h1>
      {session.data ? <p className="text-sm">{formatDateTime(session.data.start)}</p> : null}
      <p role="status" className="text-sm">
        {t(`courses.lessonStatus.${register.data.lesson_status}`)}
      </p>
      {register.data.rows.length ? (
        <Button size="sm" variant="secondary" onClick={markAll}>
          {t("courses.markAllPresent")}
        </Button>
      ) : (
        <p className="text-sm">{t("courses.nobodyInSession")}</p>
      )}
      <form
        className="space-y-3"
        aria-label={t("courses.register")}
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <ul className="space-y-2">
          {register.data.rows.map((r) => {
            const current = rows[r.student] ?? {
              outcome: r.outcome,
              reason: r.absence_reason ?? "",
            };
            const absent = !["present", "late"].includes(current.outcome);
            return (
              <li
                key={r.student}
                className="flex flex-wrap items-end gap-3 rounded-md border border-border p-3"
              >
                <span className="min-w-40 font-medium">
                  {r.student_name}
                  {r.makeup ? (
                    <span className="ml-2 text-xs text-muted-foreground">
                      {t("courses.makeup")}
                    </span>
                  ) : null}
                </span>
                <SelectField
                  label={t("courses.outcomeFor", { student: r.student_name })}
                  value={current.outcome}
                  onChange={(e) =>
                    setRows({
                      ...rows,
                      [r.student]: { ...current, outcome: e.target.value as Outcome },
                    })
                  }
                  options={OUTCOMES.map((o) => ({ value: o, label: t(`courses.outcomes.${o}`) }))}
                />
                {absent ? (
                  <TextField
                    label={t("courses.absenceReasonFor", { student: r.student_name })}
                    value={current.reason}
                    onChange={(e) =>
                      setRows({ ...rows, [r.student]: { ...current, reason: e.target.value } })
                    }
                  />
                ) : null}
              </li>
            );
          })}
        </ul>
        {save.error ? <Alert tone="danger">{save.error.message}</Alert> : null}
        {save.isSuccess ? <Alert tone="success">{t("courses.registerSaved")}</Alert> : null}
        {register.data.rows.length ? (
          <Button type="submit" disabled={save.isPending}>
            {t("courses.saveRegister")}
          </Button>
        ) : null}
      </form>
    </section>
  );
}

// --- re-enrolment (public, from the rollover email) -------------------------------------------

/** Keep (or give up) next term's place from the email link (FR-20-4 roll over). */
export function ReEnrolPage({ token }: { token: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const page = useQuery({
    queryKey: ["re-enrol", token],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/public/re-enrol/{token}", { params: { path: { token } } })),
    retry: false,
  });
  const answer = useMutation({
    mutationFn: async (confirm: boolean) =>
      unwrap(
        await api.POST("/api/v1/public/re-enrol/{token}", {
          params: { path: { token } },
          body: { confirm },
        }),
      ),
    onSuccess: (data) => queryClient.setQueryData(["re-enrol", token], data),
  });
  if (page.isError) return <PublicLayout title={t("courses.reEnrol.missing")}>{null}</PublicLayout>;
  if (!page.data) return <Spinner className="m-8 size-6" label={t("grid.loading")} />;
  const p = page.data;
  return (
    <PublicLayout title={t("courses.reEnrol.title", { student: p.student })}>
      <p>
        {t("courses.reEnrol.place", {
          course: p.course_name,
          name: p.class_name,
          term: p.term,
          date: formatDate(p.starts),
          time: p.start_time,
        })}
      </p>
      <p className="mt-2 text-sm">
        {p.mode === "opt_out" ? t("courses.reEnrol.optOut") : t("courses.reEnrol.confirm")}{" "}
        {t("courses.reEnrol.deadline", { date: formatDateTime(p.deadline) })}
      </p>
      <p role="status" className="mt-4 font-medium">
        {t(`courses.offerStatus.${p.status}`)}
      </p>
      {p.open ? (
        <div className="mt-4 flex gap-2">
          <Button onClick={() => answer.mutate(true)}>{t("courses.reEnrol.keep")}</Button>
          <Button variant="secondary" onClick={() => answer.mutate(false)}>
            {t("courses.reEnrol.leave")}
          </Button>
        </div>
      ) : null}
      {answer.error ? <Alert tone="danger">{answer.error.message}</Alert> : null}
    </PublicLayout>
  );
}
