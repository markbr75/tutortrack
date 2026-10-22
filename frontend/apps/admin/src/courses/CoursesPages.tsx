import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatDateTime, formatMoney, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  FactList,
  figureCell,
  FormPanel,
  PageHeader,
  PanelFooter,
  RegisterMark,
  registerMarkFor,
  RuledPanel,
  RuledTable,
  SelectField,
  Spinner,
  Tabs,
  TextField,
  type RegisterMarkKind,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";

import { api, useOrganisation, usePermission } from "../api";
import { PanelEmpty, PanelLoading } from "../billing/moneyUi";
import { useIsPhone } from "../billing/useIsPhone";
import { BackSeparator, RecordHeader, RecordLayout } from "../components/RecordHeader";
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
/** Class states that need nothing more: shown in faded ink. */
const QUIET = ["draft", "cancelled", "completed"];

const MARK_LABEL: Record<RegisterMarkKind, string> = {
  completed: "home.register.marks.completed",
  missed: "home.register.marks.missed",
  cancelled: "home.register.marks.cancelled",
  due: "home.register.marks.due",
  upcoming: "home.register.marks.upcoming",
};

const linkClass = "font-medium underline-offset-2 hover:underline";
const caption = "block text-xs font-normal text-muted-foreground";

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

/** A form's error, or nothing. */
function ErrorAlert({ error }: { error?: Error | null }) {
  return error ? <Alert tone="danger">{error.message}</Alert> : null;
}

/** A class's state in words: draft, cancelled and completed in faded ink. */
function ClassStatus({ status }: { status: string }) {
  const { t } = useTranslation();
  return (
    <span className={QUIET.includes(status) ? "text-muted-foreground" : undefined}>
      {t(`courses.status.${status}`)}
    </span>
  );
}

const TABS = ["classes", "courses", "terms", "rollover"] as const;
type Tab = (typeof TABS)[number];

/** Courses, classes, terms and re-enrolment (E20-T10). */
export function CoursesPage() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>("classes");
  return (
    <section>
      <PageHeader title={t("courses.title")} />
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
  const isPhone = useIsPhone();
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
  const rows = classes.data?.results ?? [];
  const when = (c: GroupClass) =>
    `${weekdayNames(c.weekdays, i18n.language)} ${c.start_time.slice(0, 5)} · ${c.term_name}`;
  return (
    <div className="space-y-6">
      <div>
        <div
          role="search"
          aria-label={t("designS6.courses.filter")}
          className="mb-4 flex flex-wrap items-center gap-2"
        >
          <SelectField
            label={t("courses.term")}
            hideLabel
            size="sm"
            value={term}
            onChange={(e) => setTerm(e.target.value)}
            options={[
              { value: "", label: t("courses.allTerms") },
              ...(terms.data?.results ?? []).map((x) => ({ value: x.id, label: x.name })),
            ]}
          />
        </div>
        <RuledTable
          framed
          caption={t("courses.tabs.classes")}
          loading={classes.isPending}
          loadingLabel={t("grid.loading")}
          empty={classes.data && !rows.length ? t("courses.noClasses") : undefined}
          columns={[
            { header: t("courses.class") },
            ...(isPhone ? [] : [{ header: t("courses.course") }, { header: t("courses.when") }]),
            { header: t("courses.places") },
            ...(isPhone ? [] : [{ header: t("courses.statusLabel") }]),
          ]}
        >
          {rows.map((c) => (
            <tr key={c.id}>
              <td>
                <Link to="/classes/$classId" params={{ classId: c.id }} className={linkClass}>
                  {c.name}
                </Link>
                {isPhone ? (
                  <span className={`${caption} tabular-nums`}>
                    {[c.course_name, when(c), t(`courses.status.${c.status}`)].join(" · ")}
                  </span>
                ) : null}
              </td>
              {isPhone ? null : (
                <>
                  <td>{c.course_name}</td>
                  <td className="tabular-nums">{when(c)}</td>
                </>
              )}
              <td className="tabular-nums">
                <span className="block">
                  {t("courses.placesTaken", { enrolled: c.enrolled, capacity: c.capacity })}
                </span>
                {c.waiting ? (
                  <span className={caption}>{t("courses.waitingCount", { count: c.waiting })}</span>
                ) : null}
              </td>
              {isPhone ? null : (
                <td>
                  <ClassStatus status={c.status} />
                </td>
              )}
            </tr>
          ))}
        </RuledTable>
      </div>
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
      <FormPanel
        title={t("courses.newClass")}
        submit={t("courses.createClass")}
        pending={create.isPending}
        error={<ErrorAlert error={create.error} />}
        onSubmit={() => create.mutate()}
        columns={3}
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
      </FormPanel>
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
  const isPhone = useIsPhone();
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
  const rows = courses.data?.results ?? [];
  return (
    <div className="space-y-6">
      <RuledTable
        framed
        caption={t("courses.tabs.courses")}
        loading={courses.isPending}
        loadingLabel={t("grid.loading")}
        empty={courses.data && !rows.length ? t("courses.noCourses") : undefined}
        columns={[
          { header: t("courses.name") },
          ...(isPhone ? [] : [{ header: t("courses.pricing") }]),
          { header: t("courses.price"), end: true, width: "w-32" },
          ...(isPhone
            ? []
            : [
                { header: t("courses.public") },
                { header: t("courses.tabs.classes"), end: true, width: "w-24" },
              ]),
        ]}
      >
        {rows.map((c: Course) => (
          <tr key={c.id}>
            <td className="font-medium">
              {c.name}
              {isPhone ? (
                <span className={caption}>
                  {[
                    t(`courses.pricingModels.${c.pricing_model}`),
                    t("designS6.courses.classCount", { count: c.classes_count }),
                  ].join(" · ")}
                </span>
              ) : null}
            </td>
            {isPhone ? null : <td>{t(`courses.pricingModels.${c.pricing_model}`)}</td>}
            <td className={figureCell}>{formatMoney(c.price, i18n.language)}</td>
            {isPhone ? null : (
              <>
                <td>
                  {c.is_public ? (
                    t("courses.yes")
                  ) : (
                    <span className="text-muted-foreground">{t("courses.no")}</span>
                  )}
                </td>
                <td className={figureCell}>{c.classes_count}</td>
              </>
            )}
          </tr>
        ))}
      </RuledTable>
      {canManage ? (
        <FormPanel
          title={t("courses.newCourse")}
          submit={t("courses.createCourse")}
          pending={create.isPending}
          error={<ErrorAlert error={create.error} />}
          onSubmit={() => create.mutate()}
          columns={3}
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
            className="text-right tabular-nums"
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
            className="text-right tabular-nums"
            value={draft.registration_fee}
            onChange={(e) => setDraft({ ...draft, registration_fee: e.target.value })}
          />
          <TextField
            label={t("courses.publicDescription")}
            value={draft.public_description}
            onChange={(e) => setDraft({ ...draft, public_description: e.target.value })}
          />
          <label className="flex items-center gap-2 text-sm sm:mt-7">
            <input
              type="checkbox"
              className="size-4"
              checked={draft.is_public}
              onChange={(e) => setDraft({ ...draft, is_public: e.target.checked })}
            />
            {t("courses.showOnWebsite")}
          </label>
        </FormPanel>
      ) : null}
    </div>
  );
}

function TermsSection() {
  const { t, i18n } = useTranslation();
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
  const date = (iso: string) => formatDate(iso, i18n.language);
  const rows = terms.data?.results ?? [];
  return (
    <div className="space-y-6">
      <RuledTable
        framed
        caption={t("courses.tabs.terms")}
        loading={terms.isPending}
        loadingLabel={t("grid.loading")}
        empty={terms.data && !rows.length ? t("courses.noTerms") : undefined}
        columns={[
          { header: t("courses.name") },
          { header: t("courses.year") },
          { header: t("courses.dates") },
          { header: t("courses.breaks") },
        ]}
      >
        {rows.map((x: Term) => (
          <tr key={x.id}>
            <td className="font-medium">{x.name}</td>
            <td>{x.academic_year_name}</td>
            <td className="tabular-nums">
              {date(x.start_date)} – {date(x.end_date)}
            </td>
            <td className="tabular-nums">
              {(x.breaks ?? [])
                .map((b) => `${b.name} (${date(b.start_date)} – ${date(b.end_date)})`)
                .join("; ") || <span className="text-muted-foreground">–</span>}
            </td>
          </tr>
        ))}
      </RuledTable>
      {canManage ? (
        <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
          <FormPanel
            title={t("courses.newYear")}
            submit={t("courses.addYear")}
            pending={addYear.isPending}
            error={<ErrorAlert error={addYear.error} />}
            onSubmit={() => addYear.mutate()}
            columns={1}
          >
            <TextField
              label={t("courses.name")}
              value={year.name}
              required
              onChange={(e) => setYear({ ...year, name: e.target.value })}
            />
            <div className="grid gap-x-4 gap-y-3 sm:grid-cols-2">
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
            </div>
          </FormPanel>
          <FormPanel
            title={t("courses.newTerm")}
            submit={t("courses.addTerm")}
            pending={addTerm.isPending}
            error={<ErrorAlert error={addTerm.error} />}
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
            <div className="-mx-5 grid gap-x-4 gap-y-3 border-t border-rule px-5 pt-4 sm:col-span-full sm:grid-cols-3">
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
            </div>
          </FormPanel>
        </div>
      ) : null}
    </div>
  );
}

function RolloverSection() {
  const { t, i18n } = useTranslation();
  const isPhone = useIsPhone();
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
  const rows = rollovers.data?.results ?? [];
  return (
    <div className="space-y-6">
      <RuledPanel
        flush
        title={t("designS6.courses.reEnrolments")}
        description={t("courses.rolloverHelp")}
      >
        <RuledTable
          caption={t("courses.tabs.rollover")}
          loading={rollovers.isPending}
          loadingLabel={t("grid.loading")}
          empty={rollovers.data && !rows.length ? t("designS6.courses.noRollovers") : undefined}
          columns={
            isPhone
              ? [{ header: t("courses.fromTo") }]
              : [
                  { header: t("courses.fromTo"), width: "min-w-64" },
                  { header: t("courses.deadline") },
                  { header: t("courses.statusLabel") },
                  { header: t("courses.answers") },
                  ...(canRun ? [{ header: t("common.actions"), hidden: true }] : []),
                ]
          }
        >
          {rows.map((r) => {
            const answers = Object.entries(r.counts)
              .map(([k, n]) => `${t(`courses.offerStatus.${k}`)}: ${n}`)
              .join(", ");
            const deadline = formatDateTime(r.deadline, i18n.language);
            const status = t(`courses.rolloverStatus.${r.status}`);
            const actions =
              canRun && r.status === "running" ? (
                <>
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => act.mutate({ id: r.id, action: "finalise" })}
                  >
                    {t("courses.finishNow")}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-muted-foreground"
                    onClick={() => act.mutate({ id: r.id, action: "cancel" })}
                  >
                    {t("courses.cancel")}
                  </Button>
                </>
              ) : null;
            // Phones: one full-width cell, the title over one caption, the actions under it.
            if (isPhone) {
              return (
                <tr key={r.id}>
                  <td>
                    <span className="font-medium">
                      {t("designS6.courses.fromTo", {
                        from: r.from_term_name,
                        to: r.to_term_name,
                      })}
                    </span>
                    <span className={`${caption} tabular-nums`}>
                      {[status, deadline, answers].filter(Boolean).join(" · ")}
                    </span>
                    {actions ? <div className="mt-2 flex flex-wrap gap-2">{actions}</div> : null}
                  </td>
                </tr>
              );
            }
            return (
              <tr key={r.id}>
                <td className="font-medium">
                  {t("designS6.courses.fromTo", { from: r.from_term_name, to: r.to_term_name })}
                </td>
                <td className="tabular-nums whitespace-nowrap">{deadline}</td>
                <td
                  className={`whitespace-nowrap ${r.status === "running" ? "" : "text-muted-foreground"}`}
                >
                  {status}
                </td>
                <td className="tabular-nums">{answers}</td>
                {canRun ? (
                  <td className="py-1.5 text-right whitespace-nowrap">
                    {actions ? <span className="inline-flex gap-2">{actions}</span> : null}
                  </td>
                ) : null}
              </tr>
            );
          })}
        </RuledTable>
        {act.error ? (
          <div className="border-t border-rule px-5 py-4">
            <ErrorAlert error={act.error} />
          </div>
        ) : null}
      </RuledPanel>
      {canRun ? (
        <FormPanel
          title={t("courses.startRollover")}
          submit={t("courses.start")}
          pending={start.isPending}
          error={<ErrorAlert error={start.error} />}
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
        </FormPanel>
      ) : null}
    </div>
  );
}

// --- one class --------------------------------------------------------------------------------

/** A class: places, roster (withdraw, transfer), enrolment, sessions and waitlist. */
export function ClassPage({ classId }: { classId: string }) {
  const { t, i18n } = useTranslation();
  const isPhone = useIsPhone();
  const queryClient = useQueryClient();
  const canManage = usePermission("courses.manage");
  const canEnrol = usePermission("courses.enrolment.manage");
  const [cancelling, setCancelling] = useState(false);
  const [reason, setReason] = useState("");
  const cancelRef = useRef<HTMLButtonElement>(null);
  const reasonRef = useRef<HTMLInputElement>(null);
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
              body: { reason },
            }),
          ),
    onSuccess: () => {
      setCancelling(false);
      refresh();
    },
  });
  const wasCancelling = useRef(false);
  useEffect(() => {
    if (cancelling) reasonRef.current?.focus();
    else if (wasCancelling.current) cancelRef.current?.focus();
    wasCancelling.current = cancelling;
  }, [cancelling]);
  if (detail.isLoading) return <Spinner label={t("grid.loading")} />;
  if (!detail.data) return <Alert tone="danger">{t("courses.notFound")}</Alert>;
  const c: GroupClass = detail.data;
  const rosterRows = roster.data ?? [];
  const active = rosterRows.filter((r) =>
    ["enrolled", "trial", "pending_payment"].includes(r.status),
  );
  const live = !["cancelled", "completed"].includes(c.status);
  const date = (iso: string) => formatDate(iso, i18n.language);
  const when = `${weekdayNames(c.weekdays, i18n.language)} ${c.start_time.slice(0, 5)}`;
  const place = c.room_name || c.location_name || (c.online ? t("designS6.courses.online") : "");
  const now = new Date();
  const firstAction = c.status !== "draft";
  const sessionRows = sessions.data ?? [];
  // The red NOW rule sits before the first session that has not ended yet (none after the last).
  const nowIndex = sessionRows.findIndex((x) => new Date(x.end) > now);
  const nowRule = (
    <tr aria-hidden="true" className="border-t-2 border-margin">
      <td
        colSpan={isPhone ? 4 : 5}
        className="py-1 text-xs font-semibold tracking-wider text-margin uppercase"
      >
        {t("home.register.now", { time: formatDate(now.toISOString(), i18n.language) })}
      </td>
    </tr>
  );

  const main = (
    <>
      {cancelling ? (
        <RuledPanel
          title={t("designS6.courses.cancelTitle")}
          footer={
            <>
              <Button
                variant="danger"
                loading={lifecycle.isPending}
                onClick={() => lifecycle.mutate("cancel")}
              >
                {t("courses.cancelClass")}
              </Button>
              <Button
                variant="ghost"
                className="text-muted-foreground"
                onClick={() => setCancelling(false)}
              >
                {t("designS6.courses.keepClass")}
              </Button>
            </>
          }
        >
          <div
            className="max-w-md"
            onKeyDown={(e) => {
              if (e.key === "Escape") setCancelling(false);
            }}
          >
            <TextField
              ref={reasonRef}
              label={t("designS6.courses.reason")}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </div>
        </RuledPanel>
      ) : null}
      <RuledPanel flush title={t("courses.roster")}>
        <RuledTable
          caption={t("courses.roster")}
          loading={roster.isPending}
          loadingLabel={t("grid.loading")}
          empty={roster.data && !rosterRows.length ? t("courses.nobodyEnrolled") : undefined}
          columns={[
            { header: t("courses.student"), width: isPhone ? undefined : "min-w-48" },
            ...(isPhone ? [] : [{ header: t("courses.statusLabel") }]),
            ...(canEnrol ? [{ header: t("common.actions"), hidden: true }] : []),
          ]}
        >
          {rosterRows.map((r) => (
            <RosterLine key={r.enrolment} row={r} classId={classId} canEnrol={canEnrol} />
          ))}
        </RuledTable>
        {rosterRows.length && !active.length ? (
          <p className="border-t border-rule px-5 py-3 text-sm text-muted-foreground">
            {t("courses.nobodyEnrolled")}
          </p>
        ) : null}
      </RuledPanel>
      {canEnrol && live ? <EnrolForm groupClass={c} onDone={refresh} /> : null}
      <RuledPanel flush title={t("courses.sessions")}>
        <RuledTable
          caption={t("courses.sessions")}
          loading={sessions.isPending}
          loadingLabel={t("grid.loading")}
          empty={
            sessions.data && !sessions.data.length ? t("designS6.courses.noSessions") : undefined
          }
          columns={[
            { header: t("courses.number"), end: true, width: "w-12" },
            { header: t("courses.date") },
            ...(isPhone ? [] : [{ header: t("courses.students"), end: true, width: "w-24" }]),
            { header: t("designS6.courses.mark"), center: true, width: "w-20" },
            { header: t("courses.register"), hidden: true },
          ]}
        >
          {sessionRows.map((s, index) => {
            const kind = registerMarkFor(s.lesson_status, s.end, now);
            return (
              <Fragment key={s.id}>
                {index === nowIndex ? nowRule : null}
                <tr>
                  <td className={figureCell}>{s.number}</td>
                  <td className="tabular-nums whitespace-nowrap">
                    {formatDateTime(s.start, i18n.language)}
                  </td>
                  {isPhone ? null : <td className={figureCell}>{s.attendees}</td>}
                  <td className="py-2">
                    <RegisterMark kind={kind} label={t(MARK_LABEL[kind])} className="mx-auto" />
                  </td>
                  <td className="text-right">
                    {s.lesson_status === "cancelled" ? (
                      <span className="text-muted-foreground">{t("courses.cancelled")}</span>
                    ) : (
                      <Link
                        to="/class-sessions/$sessionId/register"
                        params={{ sessionId: s.id }}
                        className={`${linkClass} text-link`}
                      >
                        {t("courses.register")}
                      </Link>
                    )}
                  </td>
                </tr>
              </Fragment>
            );
          })}
          {nowIndex === -1 && sessionRows.length ? nowRule : null}
        </RuledTable>
      </RuledPanel>
    </>
  );

  const waiting = waitlist.data ?? [];
  const side = (
    <>
      <RuledPanel flush title={t("designS6.courses.details")}>
        <FactList
          items={[
            [t("courses.course"), c.course_name],
            [t("courses.term"), c.term_name],
            [t("courses.when"), <span className="tabular-nums">{when}</span>],
            [
              t("courses.dates"),
              <span className="tabular-nums">
                {date(c.start_date)} – {date(c.end_date)}
              </span>,
            ],
            [t("designS6.courses.where"), place],
            [t("courses.teacher"), (c.teachers ?? []).map((x) => x.tutor_name).join(", ")],
            [
              t("courses.places"),
              <span className="tabular-nums">
                {t("courses.placesTaken", { enrolled: c.enrolled, capacity: c.capacity })} ·{" "}
                {t("courses.placesLeft", { count: c.places_left })}
              </span>,
            ],
          ]}
        />
      </RuledPanel>
      <RuledPanel
        flush
        title={t("courses.waitlist")}
        aside={
          waiting.length ? (
            <span className="text-muted-foreground tabular-nums">
              {t("courses.waitingCount", { count: waiting.length })}
            </span>
          ) : null
        }
      >
        {waitlist.isPending ? (
          <PanelLoading label={t("grid.loading")} />
        ) : !waiting.length ? (
          <PanelEmpty>{t("designS6.courses.nobodyWaiting")}</PanelEmpty>
        ) : (
          <RuledTable
            caption={t("courses.waitlist")}
            columns={[
              { header: t("courses.position"), end: true, width: "w-14" },
              { header: t("courses.student") },
            ]}
          >
            {waiting.map((w) => (
              <tr key={w.id}>
                <td className={figureCell}>{w.position ?? "–"}</td>
                <td>
                  <span className="font-medium">{w.student_name}</span>
                  <span className={`${caption} tabular-nums`}>
                    {t(`courses.waitStatus.${w.status}`)}
                    {w.offer_expires_at
                      ? ` · ${t("courses.offerUntil", { date: formatDateTime(w.offer_expires_at, i18n.language) })}`
                      : ""}
                  </span>
                </td>
              </tr>
            ))}
          </RuledTable>
        )}
      </RuledPanel>
    </>
  );

  return (
    <section>
      <RecordHeader
        back={<Link to="/courses">{t("courses.title")}</Link>}
        title={c.name}
        description={
          <span className="tabular-nums">
            <ClassStatus status={c.status} /> · {c.course_name} · {when} · {c.term_name}
          </span>
        }
        actions={
          canManage ? (
            <>
              {c.status === "draft" ? (
                <Button
                  size="sm"
                  loading={lifecycle.isPending && lifecycle.variables === "open"}
                  onClick={() => lifecycle.mutate("open")}
                >
                  {t("courses.openClass")}
                </Button>
              ) : null}
              {live && !cancelling ? (
                <Button
                  ref={cancelRef}
                  size="sm"
                  variant="ghost"
                  className={`text-muted-foreground ${firstAction ? "max-sm:-ml-3" : ""}`}
                  aria-expanded={false}
                  onClick={() => setCancelling(true)}
                >
                  {t("courses.cancelClass")}
                </Button>
              ) : null}
            </>
          ) : null
        }
      />
      {lifecycle.error ? (
        <div className="-mt-3 mb-6">
          <ErrorAlert error={lifecycle.error} />
        </div>
      ) : null}
      <RecordLayout main={main} side={side} />
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
  const { t, i18n } = useTranslation();
  const isPhone = useIsPhone();
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
  const error = withdraw.error ?? transfer.error;
  const dates =
    formatDate(row.start_date, i18n.language) +
    (row.end_date ? ` – ${formatDate(row.end_date, i18n.language)}` : "");
  const status = t(`courses.enrolmentStatus.${row.status}`);
  return (
    <tr>
      <td>
        <span className="font-medium">{row.student_name}</span>
        <span className={`${caption} tabular-nums`}>
          {(isPhone ? [status, dates] : [row.client_name, dates]).join(" · ")}
        </span>
      </td>
      {isPhone ? null : (
        <>
          <td
            className={`whitespace-nowrap ${
              attending || row.status === "pending_payment" ? "" : "text-muted-foreground"
            }`}
          >
            {status}
          </td>
        </>
      )}
      {canEnrol ? (
        <td className="py-1.5 text-right">
          {attending ? (
            <span
              className={`inline-flex items-center justify-end gap-2 ${moving || isPhone ? "flex-wrap" : ""}`}
            >
              {moving ? (
                <>
                  <SelectField
                    label={t("courses.moveTo")}
                    hideLabel
                    size="sm"
                    className="h-8 max-w-56"
                    value={target}
                    onChange={(e) => setTarget(e.target.value)}
                    options={[
                      { value: "", label: t("courses.moveTo") },
                      ...(others.data?.results ?? [])
                        .filter((x) => x.id !== classId)
                        .map((x) => ({ value: x.id, label: `${x.course_name} – ${x.name}` })),
                    ]}
                  />
                  <Button
                    size="sm"
                    disabled={!target}
                    loading={transfer.isPending}
                    onClick={() => transfer.mutate()}
                  >
                    {t("courses.move")}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-muted-foreground"
                    onClick={() => setMoving(false)}
                  >
                    {t("common.cancel")}
                  </Button>
                </>
              ) : (
                <>
                  <Button
                    size="sm"
                    variant="secondary"
                    aria-expanded={false}
                    onClick={() => setMoving(true)}
                  >
                    {t("courses.transfer")}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-muted-foreground"
                    aria-label={t("courses.withdraw", { student: row.student_name })}
                    loading={withdraw.isPending}
                    onClick={() => withdraw.mutate()}
                  >
                    {t("designS6.courses.withdraw")}
                  </Button>
                </>
              )}
            </span>
          ) : null}
          {error ? (
            <div className="mt-2 text-left">
              <ErrorAlert error={error} />
            </div>
          ) : null}
        </td>
      ) : null}
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
  const full = groupClass.places_left <= 0;
  const money = (value: { amount: string; currency: string }) => formatMoney(value, i18n.language);
  return (
    <FormPanel
      title={t("courses.enrolStudent")}
      submit={t("courses.enrol")}
      pending={enrol.isPending}
      error={<ErrorAlert error={enrol.error ?? waitlist.error} />}
      onSubmit={() => enrol.mutate()}
      lead={
        full && groupClass.waitlist_enabled ? (
          <Button
            type="button"
            variant="secondary"
            disabled={!student}
            loading={waitlist.isPending}
            onClick={() => waitlist.mutate()}
          >
            {t("courses.addToWaitlist")}
          </Button>
        ) : null
      }
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
      <div className="flex flex-col gap-2 text-sm sm:mt-7">
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            className="size-4"
            checked={trial}
            onChange={(e) => setTrial(e.target.checked)}
          />
          {t("courses.trial")}
        </label>
        {full ? (
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              className="size-4"
              checked={override}
              onChange={(e) => setOverride(e.target.checked)}
            />
            {t("courses.overrideCapacity")}
          </label>
        ) : null}
      </div>
      {q ? (
        <div
          className="space-y-1 rounded-md border border-border px-4 py-3 text-sm tabular-nums sm:col-span-full"
          aria-live="polite"
        >
          <p>
            {t("courses.feeDue", { amount: money(q.fee_due) })}
            {q.units.total && q.units.remaining < q.units.total
              ? ` ${t("courses.prorated", { remaining: q.units.remaining, total: q.units.total })}`
              : ""}
          </p>
          {q.discounts.map((d) => (
            <p key={d.name} className="text-muted-foreground">
              {d.name}: {money(d.amount)}
            </p>
          ))}
          <p className="font-semibold">{t("courses.dueNow", { amount: money(q.due_now) })}</p>
          {q.problems?.length ? (
            <Alert tone="warning" className="mt-2">
              {q.problems.join(" ")}
            </Alert>
          ) : null}
        </div>
      ) : null}
    </FormPanel>
  );
}

// --- register ---------------------------------------------------------------------------------

/** The class register: everyone at once, with absence reasons (FR-20-6). */
export function RegisterPage({ sessionId }: { sessionId: string }) {
  const { t, i18n } = useTranslation();
  const isPhone = useIsPhone();
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
  if (!register.data) return <Spinner label={t("grid.loading")} />;
  const markAll = () =>
    setRows(
      Object.fromEntries(
        register.data.rows.map((r) => [r.student, { outcome: "present" as Outcome, reason: "" }]),
      ),
    );
  const s = session.data;
  const back: ReactNode = (
    <>
      <Link to="/courses">{t("courses.title")}</Link>
      {s ? (
        <>
          <BackSeparator />
          <Link to="/classes/$classId" params={{ classId: s.group_class }}>
            {s.class_name}
          </Link>
        </>
      ) : null}
    </>
  );
  const status = register.data.lesson_status;
  return (
    <section>
      <RecordHeader
        back={back}
        title={t("courses.registerFor", {
          name: s ? `${s.course_name} – ${s.class_name}` : "",
        })}
        description={
          <span className="tabular-nums">
            {s ? `${formatDateTime(s.start, i18n.language)} · ` : ""}
            <span role="status">{t(`courses.lessonStatus.${status}`)}</span>
          </span>
        }
      />
      <form
        aria-label={t("courses.register")}
        className="max-w-4xl"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <RuledPanel
          flush
          title={t("courses.students")}
          aside={
            register.data.rows.length ? (
              <Button type="button" size="sm" variant="secondary" onClick={markAll}>
                {t("courses.markAllPresent")}
              </Button>
            ) : null
          }
        >
          {register.data.rows.length ? (
            <RuledTable
              caption={t("courses.register")}
              columns={[
                { header: t("courses.student"), width: isPhone ? undefined : "min-w-48" },
                {
                  header: t("designS6.courses.mark"),
                  center: true,
                  width: isPhone ? "w-14" : "w-20",
                },
                ...(isPhone
                  ? []
                  : [
                      { header: t("designS6.courses.attendance"), width: "w-56" },
                      { header: t("designS6.courses.absenceReason") },
                    ]),
              ]}
            >
              {register.data.rows.map((r) => {
                const changed = rows[r.student];
                const current = changed ?? {
                  outcome: r.outcome,
                  reason: r.absence_reason ?? "",
                };
                const absent = !["present", "late"].includes(current.outcome);
                const kind: RegisterMarkKind =
                  !changed && status === "planned"
                    ? registerMarkFor("planned", s?.end ?? new Date().toISOString())
                    : current.outcome === "present" || current.outcome === "late"
                      ? "completed"
                      : current.outcome.startsWith("cancelled")
                        ? "cancelled"
                        : "missed";
                const reasonField = absent ? (
                  <TextField
                    label={t("courses.absenceReasonFor", { student: r.student_name })}
                    hideLabel
                    size="sm"
                    placeholder={isPhone ? t("designS6.courses.absenceReason") : undefined}
                    value={current.reason}
                    onChange={(e) =>
                      setRows({
                        ...rows,
                        [r.student]: { ...current, reason: e.target.value },
                      })
                    }
                  />
                ) : null;
                const select = (
                  <SelectField
                    label={t("courses.outcomeFor", { student: r.student_name })}
                    hideLabel
                    size="sm"
                    value={current.outcome}
                    onChange={(e) =>
                      setRows({
                        ...rows,
                        [r.student]: { ...current, outcome: e.target.value as Outcome },
                      })
                    }
                    options={OUTCOMES.map((o) => ({
                      value: o,
                      label: t(`courses.outcomes.${o}`),
                    }))}
                  />
                );
                const name = (
                  <>
                    <span className="font-medium">{r.student_name}</span>
                    {r.makeup ? <span className={caption}>{t("courses.makeup")}</span> : null}
                  </>
                );
                const mark = (
                  <td className="py-3">
                    <RegisterMark
                      kind={kind}
                      label={
                        kind === "due" || kind === "upcoming"
                          ? t(MARK_LABEL[kind])
                          : t(`courses.outcomes.${current.outcome}`)
                      }
                      className="mx-auto"
                    />
                  </td>
                );
                // On phones the controls stack under the name, so each select has the row's width.
                return isPhone ? (
                  <tr key={r.student}>
                    <td className="space-y-2 py-3">
                      <div>{name}</div>
                      {select}
                      {reasonField}
                    </td>
                    {mark}
                  </tr>
                ) : (
                  <tr key={r.student}>
                    <td className="py-3">{name}</td>
                    {mark}
                    <td className="py-1.5">{select}</td>
                    <td className="py-1.5">{reasonField}</td>
                  </tr>
                );
              })}
            </RuledTable>
          ) : (
            <PanelEmpty>{t("courses.nobodyInSession")}</PanelEmpty>
          )}
          {save.error ? (
            <div className="border-t border-rule px-5 py-4">
              <ErrorAlert error={save.error} />
            </div>
          ) : null}
          {register.data.rows.length ? (
            <PanelFooter>
              <Button type="submit" loading={save.isPending}>
                {t("courses.saveRegister")}
              </Button>
              {save.isSuccess ? (
                <p role="status" className="text-success">
                  {t("courses.registerSaved")}
                </p>
              ) : null}
            </PanelFooter>
          ) : null}
        </RuledPanel>
      </form>
    </section>
  );
}

// --- re-enrolment (public, from the rollover email) -------------------------------------------

/** Keep (or give up) next term's place from the email link (FR-20-4 roll over). */
export function ReEnrolPage({ token }: { token: string }) {
  const { t, i18n } = useTranslation();
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
  if (!page.data) return <PublicLayout loading />;
  const p = page.data;
  return (
    <PublicLayout title={t("courses.reEnrol.title", { student: p.student })}>
      <div className="space-y-6">
        <div className="space-y-1">
          <p className="tabular-nums">
            {t("courses.reEnrol.place", {
              course: p.course_name,
              name: p.class_name,
              term: p.term,
              date: formatDate(p.starts, i18n.language),
              time: p.start_time,
            })}
          </p>
          <p className="text-sm text-muted-foreground tabular-nums">
            {p.mode === "opt_out" ? t("courses.reEnrol.optOut") : t("courses.reEnrol.confirm")}{" "}
            {/* The reply-by date waits on the family while the answer is open: margin red. */}
            <span className={p.open ? "font-medium text-margin" : undefined}>
              {t(p.mode === "opt_out" ? "courses.reEnrol.deadline" : "designS6.courses.answerBy", {
                date: formatDateTime(p.deadline, i18n.language),
              })}
            </span>
          </p>
        </div>
        <div className="border-y border-border py-3">
          <p role="status" className="text-base font-semibold">
            {t(`courses.offerStatus.${p.status}`)}
          </p>
        </div>
        {p.open ? (
          <div className="flex flex-wrap gap-2">
            <Button
              loading={answer.isPending && answer.variables === true}
              onClick={() => answer.mutate(true)}
            >
              {t("courses.reEnrol.keep")}
            </Button>
            <Button
              variant="secondary"
              loading={answer.isPending && answer.variables === false}
              onClick={() => answer.mutate(false)}
            >
              {t("courses.reEnrol.leave")}
            </Button>
          </div>
        ) : null}
        <ErrorAlert error={answer.error} />
      </div>
    </PublicLayout>
  );
}
