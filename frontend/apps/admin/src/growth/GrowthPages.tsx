import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatDateTime, formatMoney, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  CheckboxField,
  PageHeader,
  Panel,
  PanelFooter,
  figureCell,
  RuledTable,
  SelectField,
  Spinner,
  Tabs,
  TextAreaField,
  TextField,
  type RuledColumn,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Star } from "lucide-react";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";

import { api, fieldErrors, useOrganisation, usePermission } from "../api";
import { useIsPhone } from "../billing/useIsPhone";
import { RecordLayout } from "../components/RecordHeader";
import { PublicLayout } from "../layout/PublicLayout";

type Review = components["schemas"]["Review"];
type Referral = components["schemas"]["Referral"];
type Program = components["schemas"]["ReferralProgram"];
type Affiliate = components["schemas"]["Affiliate"];
type Statement = components["schemas"]["AffiliateStatement"];
type MoneyValue = { amount: string; currency: string };

const PAGE = { page_size: 200 };

/** A ruled panel holding one register table (the panel's title names the table too). */
function TablePanel({
  caption,
  columns,
  empty,
  aside,
  footer,
  waiting = false,
  children,
}: {
  caption: string;
  columns: RuledColumn[];
  empty?: string | false;
  aside?: ReactNode;
  footer?: ReactNode;
  /** Margin red while something in the table waits on the business. */
  waiting?: boolean;
  children: ReactNode;
}) {
  return (
    <Panel title={caption} aside={aside} footer={footer} rule={waiting ? "margin" : "border"} flush>
      <RuledTable caption={caption} columns={columns} empty={empty || undefined}>
        {children}
      </RuledTable>
    </Panel>
  );
}

/** A form in a ruled panel: fields stacked, the one submit in the ruled footer. */
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
    <Panel title={title} flush>
      <form
        aria-label={title}
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          onSubmit();
        }}
      >
        <div className="space-y-3 px-5 py-4">
          {children}
          {error ? <Alert tone="danger">{error.message}</Alert> : null}
        </div>
        <PanelFooter>
          <Button type="submit" size="sm" loading={pending}>
            {submit}
          </Button>
        </PanelFooter>
      </form>
    </Panel>
  );
}

/** Five drawn stars, the rated number filled in ink and the rest pale. */
function StarRow({ rating, size = "size-3.5" }: { rating: number; size?: string }) {
  return (
    <span aria-hidden="true" className="inline-flex gap-0.5 align-[-2px]">
      {[1, 2, 3, 4, 5].map((n) => (
        <Star
          key={n}
          strokeWidth={1.75}
          className={n <= rating ? `${size} fill-current text-foreground` : `${size} text-field`}
        />
      ))}
    </span>
  );
}

/** Stars shown visually, with the rating as text for screen readers. */
export function Stars({ rating }: { rating: number }) {
  const { t } = useTranslation();
  return (
    <span className="whitespace-nowrap">
      <StarRow rating={rating} />
      <span className="sr-only">{t("reviews.stars", { count: rating })}</span>
    </span>
  );
}

function money(value: MoneyValue | null | undefined, locale: string): string {
  return value ? formatMoney(value, locale) : "–";
}

const quiet = "text-muted-foreground";
const ghost = "text-muted-foreground";

const TABS = [
  { key: "reviews", permission: "growth.review.view" },
  { key: "requests", permission: "growth.review.view" },
  { key: "referrals", permission: "growth.referral.view" },
  { key: "affiliates", permission: "growth.affiliate.view" },
  { key: "statements", permission: "growth.affiliate.view" },
  { key: "tutorReferrals", permission: "growth.tutor_referral.view" },
  { key: "settings", permission: "org.settings.view" },
] as const;
type Tab = (typeof TABS)[number]["key"];

/** Reviews, referrals and affiliates (E25). */
export function GrowthPage() {
  const { t } = useTranslation();
  const allowed = {
    "growth.review.view": usePermission("growth.review.view"),
    "growth.referral.view": usePermission("growth.referral.view"),
    "growth.affiliate.view": usePermission("growth.affiliate.view"),
    "growth.tutor_referral.view": usePermission("growth.tutor_referral.view"),
    "org.settings.view": usePermission("org.settings.view"),
  };
  const tabs = TABS.filter((tab) => allowed[tab.permission]);
  const [tab, setTab] = useState<Tab>(tabs[0]?.key ?? "reviews");
  if (!tabs.length) return <Alert tone="danger">{t("referrals.forbidden")}</Alert>;
  return (
    <section>
      <PageHeader title={t("referrals.title")} />
      <Tabs
        label={t("referrals.title")}
        tabs={tabs.map(({ key }) => ({ key, label: t(`referrals.tabs.${key}`) }))}
        value={tab}
        onChange={setTab}
      >
        {tab === "reviews" ? <ReviewsSection /> : null}
        {tab === "requests" ? <RequestsSection /> : null}
        {tab === "referrals" ? <ReferralsSection /> : null}
        {tab === "affiliates" ? <AffiliatesSection /> : null}
        {tab === "statements" ? <StatementsSection /> : null}
        {tab === "tutorReferrals" ? <TutorReferralsSection /> : null}
        {tab === "settings" ? <SettingsSection /> : null}
      </Tabs>
    </section>
  );
}

// --- reviews (T01, T02) -------------------------------------------------------------------------

function ReviewsSection() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const canManage = usePermission("growth.review.manage");
  const phone = useIsPhone();
  const [status, setStatus] = useState<string>("pending");
  const [replying, setReplying] = useState<string | null>(null);
  const [reply, setReply] = useState("");
  const summary = useQuery({
    queryKey: ["reviews", "summary"],
    queryFn: async () => unwrap(await api.GET("/api/v1/reviews/summary")),
  });
  const reviews = useQuery({
    queryKey: ["reviews", status],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/reviews", {
          params: {
            query: { ...PAGE, ...(status ? { status: status as Review["status"] } : {}) },
          },
        }),
      ),
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["reviews"] });
  const act = useMutation({
    mutationFn: async ({
      id,
      verb,
    }: {
      id: string;
      verb: "approve" | "hide" | "publish" | "unpublish";
    }) => {
      const path = { params: { path: { id } } };
      if (verb === "approve") return unwrap(await api.POST("/api/v1/reviews/{id}/approve", path));
      if (verb === "hide") return unwrap(await api.POST("/api/v1/reviews/{id}/hide", path));
      if (verb === "publish") return unwrap(await api.POST("/api/v1/reviews/{id}/publish", path));
      return unwrap(await api.POST("/api/v1/reviews/{id}/unpublish", path));
    },
    onSuccess: refresh,
  });
  const respond = useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.POST("/api/v1/reviews/{id}/respond", {
          params: { path: { id } },
          body: { response: reply },
        }),
      ),
    onSuccess: () => {
      setReplying(null);
      setReply("");
      void refresh();
    },
  });
  const rows = reviews.data?.results ?? [];
  return (
    <div className="space-y-4">
      <div
        className="flex flex-wrap items-center gap-2"
        role="search"
        aria-label={t("reviews.listTitle")}
      >
        <SelectField
          label={t("reviews.filter")}
          hideLabel
          size="sm"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          options={[
            { value: "pending", label: t("reviews.status.pending") },
            { value: "approved", label: t("reviews.status.approved") },
            { value: "hidden", label: t("reviews.status.hidden") },
            { value: "", label: t("reviews.all") },
          ]}
        />
      </div>
      {act.error ? <Alert tone="danger">{act.error.message}</Alert> : null}
      {reviews.isPending ? (
        <Spinner label={t("grid.loading")} />
      ) : (
        <TablePanel
          caption={t("reviews.listTitle")}
          waiting={status === "pending" && rows.length > 0}
          aside={
            summary.data ? (
              <span role="status" className="text-muted-foreground">
                {summary.data.average === null
                  ? t("reviews.noRatings")
                  : t("reviews.summary", {
                      average: summary.data.average.toLocaleString(i18n.language),
                      count: summary.data.count,
                    })}
              </span>
            ) : null
          }
          empty={!rows.length && t("reviews.empty")}
          columns={
            phone
              ? [{ header: t("reviews.review") }]
              : [
                  { header: t("reviews.rating") },
                  { header: t("reviews.review"), width: "min-w-64" },
                  { header: t("reviews.tutor") },
                  { header: t("reviews.status.label") },
                  { header: t("referrals.actions"), hidden: true },
                ]
          }
        >
          {rows.map((r) => {
            const status = (
              <span className={r.status === "pending" ? "font-semibold text-margin" : undefined}>
                {t(`reviews.status.${r.status}`)}
              </span>
            );
            const who = [r.reviewer_name, r.client_name, ...(phone ? [r.tutor_name] : [])]
              .filter(Boolean)
              .join(" · ");
            const replyForm =
              replying === r.id ? (
                <form
                  className="mt-2 flex flex-wrap items-end gap-2"
                  aria-label={t("reviews.reply")}
                  onSubmit={(e) => {
                    e.preventDefault();
                    respond.mutate(r.id);
                  }}
                >
                  <div className="min-w-48 flex-1">
                    <TextField
                      label={t("reviews.reply")}
                      size="sm"
                      value={reply}
                      onChange={(e) => setReply(e.target.value)}
                    />
                  </div>
                  <Button type="submit" size="sm" className="h-9" loading={respond.isPending}>
                    {t("reviews.sendReply")}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className={`h-9 ${ghost}`}
                    onClick={() => setReplying(null)}
                  >
                    {t("common.cancel")}
                  </Button>
                </form>
              ) : null;
            const actions = canManage ? (
              <div
                className={phone ? "mt-2 flex flex-wrap gap-1" : "flex flex-wrap justify-end gap-1"}
              >
                {r.status !== "approved" ? (
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => act.mutate({ id: r.id, verb: "approve" })}
                  >
                    {t("reviews.approve")}
                  </Button>
                ) : null}
                {r.status === "approved" && r.publish_consent && r.text ? (
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() =>
                      act.mutate({
                        id: r.id,
                        verb: r.published_as_testimonial ? "unpublish" : "publish",
                      })
                    }
                  >
                    {r.published_as_testimonial ? t("reviews.unpublish") : t("reviews.publish")}
                  </Button>
                ) : null}
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setReplying(r.id);
                    setReply(r.response);
                  }}
                >
                  {t("reviews.reply")}
                </Button>
                {r.status !== "hidden" ? (
                  <Button
                    size="sm"
                    variant="ghost"
                    className={ghost}
                    onClick={() => act.mutate({ id: r.id, verb: "hide" })}
                  >
                    {t("reviews.hide")}
                  </Button>
                ) : null}
              </div>
            ) : null;
            const body = (
              <>
                <p>{r.text || <span className={quiet}>{t("reviews.noComment")}</span>}</p>
                <p className="text-xs text-muted-foreground">
                  {who} ·{" "}
                  <span className="tabular-nums">{formatDate(r.created_at, i18n.language)}</span>
                </p>
                {r.response ? (
                  <p className="mt-1.5 text-sm">
                    <span className="font-medium">{t("reviews.ourReply")}:</span> {r.response}
                  </p>
                ) : null}
                {replyForm}
              </>
            );
            if (phone) {
              return (
                <tr key={r.id}>
                  <td>
                    <p className="mb-1 flex flex-wrap items-center gap-x-3">
                      <Stars rating={r.rating} />
                      {status}
                    </p>
                    {body}
                    {actions}
                  </td>
                </tr>
              );
            }
            return (
              <tr key={r.id}>
                <td>
                  <Stars rating={r.rating} />
                </td>
                <td>{body}</td>
                <td className="whitespace-nowrap">{r.tutor_name || t("reviews.business")}</td>
                <td className="min-w-32">
                  {status}
                  {r.published_as_testimonial ? (
                    <span className="block text-xs text-muted-foreground">
                      {t("reviews.onWebsite")}
                    </span>
                  ) : null}
                </td>
                <td className="text-right">{actions}</td>
              </tr>
            );
          })}
        </TablePanel>
      )}
    </div>
  );
}

function useClientsAndTutors() {
  const clients = useQuery({
    queryKey: ["clients", "all"],
    queryFn: async () => unwrap(await api.GET("/api/v1/clients", { params: { query: PAGE } })),
  });
  const tutors = useQuery({
    queryKey: ["tutors", "active"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/tutors", {
          params: { query: { status: ["active"], page_size: 200 } },
        }),
      ),
  });
  return { clients, tutors };
}

function RequestsSection() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const canManage = usePermission("growth.review.manage");
  const phone = useIsPhone();
  const { clients, tutors } = useClientsAndTutors();
  const [client, setClient] = useState("");
  const [tutor, setTutor] = useState("");
  const requests = useQuery({
    queryKey: ["review-requests"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/review-requests", { params: { query: PAGE } })),
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["review-requests"] });
  const ask = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/review-requests", {
          body: { client, tutor: tutor || null },
        }),
      ),
    onSuccess: refresh,
  });
  const cancel = useMutation({
    mutationFn: async (id: string) =>
      unwrap(await api.POST("/api/v1/review-requests/{id}/cancel", { params: { path: { id } } })),
    onSuccess: refresh,
  });
  const rows = requests.data?.results ?? [];
  return (
    <RecordLayout
      main={
        requests.isPending ? (
          <Spinner label={t("grid.loading")} />
        ) : (
          <TablePanel
            caption={t("reviews.requestsTitle")}
            empty={!rows.length && t("reviews.noRequests")}
            columns={[
              { header: t("reviews.client") },
              ...(phone
                ? []
                : [
                    { header: t("reviews.trigger.label") },
                    { header: t("reviews.status.label") },
                    { header: t("reviews.expires") },
                  ]),
              { header: t("referrals.actions"), hidden: true },
            ]}
          >
            {rows.map((r) => (
              <tr key={r.id}>
                <td>
                  <span className="font-medium">{r.client_name}</span>
                  <span className="block text-xs text-muted-foreground">
                    {[
                      r.tutor_name || t("reviews.business"),
                      ...(phone
                        ? [
                            t(`reviews.requestStatus.${r.status}`),
                            `${t("reviews.expires")} ${formatDate(r.expires_at, i18n.language)}`,
                          ]
                        : []),
                    ].join(" · ")}
                  </span>
                </td>
                {phone ? null : (
                  <>
                    <td>{t(`reviews.trigger.${r.trigger}`)}</td>
                    <td>
                      <span
                        className={
                          r.status === "expired" || r.status === "cancelled" ? quiet : undefined
                        }
                      >
                        {t(`reviews.requestStatus.${r.status}`)}
                      </span>
                    </td>
                    <td className="whitespace-nowrap tabular-nums">
                      {formatDate(r.expires_at, i18n.language)}
                    </td>
                  </>
                )}
                <td className="text-right">
                  {canManage && (r.status === "pending" || r.status === "reminded") ? (
                    <Button
                      size="sm"
                      variant="ghost"
                      className={ghost}
                      onClick={() => cancel.mutate(r.id)}
                    >
                      {t("referrals.cancel")}
                    </Button>
                  ) : null}
                </td>
              </tr>
            ))}
          </TablePanel>
        )
      }
      side={
        canManage ? (
          <FormCard
            title={t("reviews.ask")}
            submit={t("reviews.askSubmit")}
            pending={ask.isPending}
            error={ask.error}
            onSubmit={() => ask.mutate()}
          >
            <SelectField
              label={t("reviews.client")}
              required
              value={client}
              onChange={(e) => setClient(e.target.value)}
              options={[
                { value: "", label: t("referrals.choose") },
                ...(clients.data?.results ?? []).map((c) => ({
                  value: c.id,
                  label: c.display_name,
                })),
              ]}
            />
            <SelectField
              label={t("reviews.tutor")}
              value={tutor}
              onChange={(e) => setTutor(e.target.value)}
              options={[
                { value: "", label: t("reviews.business") },
                ...(tutors.data?.results ?? []).map((x) => ({ value: x.id, label: x.full_name })),
              ]}
            />
          </FormCard>
        ) : undefined
      }
    />
  );
}

// --- referrals (T03) ----------------------------------------------------------------------------

function ProgramForm({ program, currency }: { program: Program | null; currency: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [form, setForm] = useState({
    name: program?.name ?? t("referrals.defaultName"),
    reward: program?.referrer_reward.amount ?? "20.00",
    kind: program?.referrer_reward_kind ?? "credit",
    milestone: program?.milestone ?? "first_payment",
    lessons: String(program?.milestone_lessons ?? 1),
    discount: program?.referee_discount_percent ?? "",
    deadline: String(program?.deadline_days ?? 180),
    limit: program?.max_rewards_per_period ? String(program.max_rewards_per_period) : "",
  });
  const set = (key: keyof typeof form) => (value: string) => setForm({ ...form, [key]: value });
  const save = useMutation({
    mutationFn: async () => {
      const body = {
        name: form.name,
        referrer_reward: {
          amount: form.reward,
          currency: program?.referrer_reward.currency ?? currency,
        },
        referrer_reward_kind: form.kind as Program["referrer_reward_kind"],
        milestone: form.milestone as Program["milestone"],
        milestone_lessons: Number(form.lessons) || 1,
        referee_discount_percent: form.discount || null,
        deadline_days: Number(form.deadline) || 180,
        max_rewards_per_period: form.limit ? Number(form.limit) : null,
      };
      return program
        ? unwrap(
            await api.PATCH("/api/v1/referral-programs/{id}", {
              params: { path: { id: program.id } },
              body,
            }),
          )
        : unwrap(await api.POST("/api/v1/referral-programs", { body }));
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["referral-programs"] }),
  });
  const errors = fieldErrors(save.error);
  return (
    <FormCard
      title={t("referrals.program")}
      submit={t("referrals.saveProgram")}
      pending={save.isPending}
      error={save.error}
      onSubmit={() => save.mutate()}
    >
      <TextField
        label={t("referrals.name")}
        required
        value={form.name}
        onChange={(e) => set("name")(e.target.value)}
        error={errors.name}
      />
      <TextField
        label={t("referrals.reward")}
        inputMode="decimal"
        className="tabular-nums"
        required
        value={form.reward}
        onChange={(e) => set("reward")(e.target.value)}
        error={errors.referrer_reward}
      />
      <SelectField
        label={t("referrals.rewardKind")}
        value={form.kind}
        onChange={(e) => set("kind")(e.target.value)}
        options={[
          { value: "credit", label: t("referrals.kinds.credit") },
          { value: "free_lesson", label: t("referrals.kinds.free_lesson") },
        ]}
      />
      <SelectField
        label={t("referrals.milestone")}
        value={form.milestone}
        onChange={(e) => set("milestone")(e.target.value)}
        options={[
          { value: "first_payment", label: t("referrals.milestones.first_payment") },
          { value: "lessons", label: t("referrals.milestones.lessons") },
        ]}
      />
      {form.milestone === "lessons" ? (
        <TextField
          label={t("referrals.lessons")}
          type="number"
          min={1}
          className="w-24 text-right"
          value={form.lessons}
          onChange={(e) => set("lessons")(e.target.value)}
        />
      ) : null}
      <TextField
        label={t("referrals.discount")}
        hint={t("referrals.discountHint")}
        inputMode="decimal"
        className="w-24 text-right"
        value={form.discount}
        onChange={(e) => set("discount")(e.target.value)}
        error={errors.referee_discount_percent}
      />
      <TextField
        label={t("referrals.deadline")}
        type="number"
        min={1}
        className="w-24 text-right"
        value={form.deadline}
        onChange={(e) => set("deadline")(e.target.value)}
      />
      <TextField
        label={t("referrals.limit")}
        hint={t("referrals.limitHint")}
        type="number"
        min={1}
        className="w-24 text-right"
        value={form.limit}
        onChange={(e) => set("limit")(e.target.value)}
      />
    </FormCard>
  );
}

function ReferralsSection() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const canManage = usePermission("growth.referral.manage");
  const phone = useIsPhone();
  const { data: org } = useOrganisation();
  const programs = useQuery({
    queryKey: ["referral-programs"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/referral-programs", { params: { query: PAGE } })),
  });
  const referrals = useQuery({
    queryKey: ["referrals"],
    queryFn: async () => unwrap(await api.GET("/api/v1/referrals", { params: { query: PAGE } })),
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["referrals"] });
  const act = useMutation({
    mutationFn: async ({ id, verb }: { id: string; verb: "approve" | "cancel" }) =>
      verb === "approve"
        ? unwrap(await api.POST("/api/v1/referrals/{id}/approve", { params: { path: { id } } }))
        : unwrap(
            await api.POST("/api/v1/referrals/{id}/cancel", {
              params: { path: { id } },
              body: { reason: "" },
            }),
          ),
    onSuccess: refresh,
  });
  const program = programs.data?.results.find((p) => p.active) ?? null;
  const rows = referrals.data?.results ?? [];
  return (
    <RecordLayout
      main={
        <>
          {act.error ? <Alert tone="danger">{act.error.message}</Alert> : null}
          {referrals.isPending ? (
            <Spinner label={t("grid.loading")} />
          ) : (
            <TablePanel
              caption={t("referrals.listTitle")}
              waiting={rows.some((r) => r.status === "blocked")}
              empty={!rows.length && t("referrals.empty")}
              columns={[
                { header: t("referrals.referee"), width: phone ? undefined : "min-w-56" },
                ...(phone ? [] : [{ header: t("referrals.statusLabel"), width: "min-w-40" }]),
                {
                  header: t("referrals.rewardLabel"),
                  end: true,
                  width: phone ? undefined : "w-32",
                },
              ]}
            >
              {rows.map((r: Referral) => {
                const actions = canManage ? (
                  <div className={`mt-2 flex gap-1 ${phone ? "flex-wrap" : "whitespace-nowrap"}`}>
                    {r.status === "blocked" ? (
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => act.mutate({ id: r.id, verb: "approve" })}
                      >
                        {t("referrals.approve")}
                      </Button>
                    ) : null}
                    {["pending", "converted", "blocked"].includes(r.status) ? (
                      <Button
                        size="sm"
                        variant="ghost"
                        className={r.status !== "blocked" ? `-ml-3 ${ghost}` : ghost}
                        onClick={() => act.mutate({ id: r.id, verb: "cancel" })}
                      >
                        {t("referrals.cancel")}
                      </Button>
                    ) : null}
                  </div>
                ) : null;
                return (
                  <tr key={r.id}>
                    <td>
                      {r.referee_name}
                      <span className="block text-xs text-muted-foreground tabular-nums">
                        {`${t("referrals.referrer")} ${r.referrer_name} · `}
                        <span className="whitespace-nowrap">
                          {formatDate(r.created_at, i18n.language)}
                        </span>
                      </span>
                      {phone ? (
                        <>
                          <span
                            className={`block ${r.status === "blocked" ? "font-semibold text-margin" : ""}`}
                          >
                            {[
                              t(`referrals.status.${r.status}`),
                              ...((r.fraud_flags as string[] | null) ?? []).map((f) =>
                                t(`referrals.flags.${f}`),
                              ),
                            ].join(" · ")}
                          </span>
                          {actions}
                        </>
                      ) : null}
                    </td>
                    {phone ? null : (
                      <td>
                        <span
                          className={
                            r.status === "blocked"
                              ? "font-semibold whitespace-nowrap text-margin"
                              : "whitespace-nowrap"
                          }
                        >
                          {t(`referrals.status.${r.status}`)}
                        </span>
                        {Array.isArray(r.fraud_flags) && r.fraud_flags.length ? (
                          <span className="block text-xs text-muted-foreground">
                            {(r.fraud_flags as string[])
                              .map((f) => t(`referrals.flags.${f}`))
                              .join(", ")}
                          </span>
                        ) : null}
                        {actions}
                      </td>
                    )}
                    <td className={figureCell}>{money(r.referrer_credit, i18n.language)}</td>
                  </tr>
                );
              })}
            </TablePanel>
          )}
        </>
      }
      side={
        canManage && programs.data ? (
          <ProgramForm
            key={program?.id ?? "new"}
            program={program}
            currency={org?.default_currency ?? "GBP"}
          />
        ) : undefined
      }
    />
  );
}

// --- affiliates (T04, T05) ----------------------------------------------------------------------

function AffiliatesSection() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canManage = usePermission("growth.affiliate.manage");
  const phone = useIsPhone();
  const { data: org } = useOrganisation();
  const [form, setForm] = useState({ name: "", email: "", kind: "individual" });
  const [link, setLink] = useState({ affiliate: "", name: "", landing_path: "/" });
  const [rule, setRule] = useState({
    name: "",
    kind: "percent",
    percent: "10",
    bounty: "",
    months: "12",
  });
  const affiliates = useQuery({
    queryKey: ["affiliates"],
    queryFn: async () => unwrap(await api.GET("/api/v1/affiliates", { params: { query: PAGE } })),
  });
  const links = useQuery({
    queryKey: ["affiliate-links"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/affiliate-links", { params: { query: PAGE } })),
  });
  const rules = useQuery({
    queryKey: ["commission-rules"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/commission-rules", { params: { query: PAGE } })),
  });
  const create = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/affiliates", {
          body: { ...form, kind: form.kind as Affiliate["kind"] & string },
        }),
      ),
    onSuccess: () => {
      setForm({ name: "", email: "", kind: "individual" });
      void queryClient.invalidateQueries({ queryKey: ["affiliates"] });
      void queryClient.invalidateQueries({ queryKey: ["affiliate-links"] });
    },
  });
  const invite = useMutation({
    mutationFn: async (id: string) =>
      unwrap(await api.POST("/api/v1/affiliates/{id}/invite", { params: { path: { id } } })),
  });
  const addLink = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/affiliate-links", { body: link })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["affiliate-links"] }),
  });
  const saveRule = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/commission-rules", {
          body: {
            name: rule.name,
            kind: rule.kind as "percent" | "bounty",
            percent: rule.kind === "percent" ? rule.percent : null,
            bounty:
              rule.kind === "bounty"
                ? { amount: rule.bounty, currency: org?.default_currency ?? "GBP" }
                : null,
            duration_months: rule.months ? Number(rule.months) : null,
          },
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["commission-rules"] }),
  });
  const errors = fieldErrors(create.error);
  const people = affiliates.data?.results ?? [];
  if (affiliates.isPending) return <Spinner label={t("grid.loading")} />;
  return (
    <RecordLayout
      main={
        <>
          {invite.isSuccess ? (
            <Alert tone="success">{t("referrals.invited", { email: invite.data.email })}</Alert>
          ) : null}
          {invite.error ? <Alert tone="danger">{invite.error.message}</Alert> : null}
          <TablePanel
            caption={t("referrals.affiliatesTitle")}
            empty={!people.length && t("referrals.noAffiliates")}
            columns={[
              { header: t("referrals.name") },
              ...(phone
                ? []
                : [{ header: t("referrals.statusLabel") }, { header: t("referrals.payout") }]),
              { header: t("referrals.actions"), hidden: true },
            ]}
          >
            {people.map((a) => (
              <tr key={a.id}>
                <td>
                  <span className="font-medium">{a.name}</span>
                  <span className="block text-xs break-all text-muted-foreground">
                    {phone
                      ? [
                          a.email,
                          t(`referrals.affiliateStatus.${a.status ?? "active"}`),
                          t(`referrals.payoutMethods.${a.payout_method ?? "manual"}`),
                        ].join(" · ")
                      : a.email}
                  </span>
                </td>
                {phone ? null : (
                  <>
                    <td>{t(`referrals.affiliateStatus.${a.status ?? "active"}`)}</td>
                    <td>
                      {t(`referrals.payoutMethods.${a.payout_method ?? "manual"}`)}
                      {a.bank_hint ? (
                        <span className="block text-xs text-muted-foreground tabular-nums">
                          {a.bank_hint}
                        </span>
                      ) : null}
                    </td>
                  </>
                )}
                <td className="text-right whitespace-nowrap">
                  {canManage && !a.has_login ? (
                    <Button size="sm" variant="secondary" onClick={() => invite.mutate(a.id)}>
                      {t("referrals.invite")}
                    </Button>
                  ) : a.has_login ? (
                    <span className={quiet}>{t("referrals.hasLogin")}</span>
                  ) : null}
                </td>
              </tr>
            ))}
          </TablePanel>
          <TablePanel
            caption={t("referrals.linksTitle")}
            empty={!links.data?.results.length && t("designS8.growth.noLinks")}
            columns={[
              { header: t("referrals.code") },
              ...(phone
                ? []
                : [{ header: t("referrals.affiliate") }, { header: t("referrals.landingPath") }]),
              { header: t("referrals.clicks"), end: true },
            ]}
          >
            {links.data?.results.map((l) => (
              <tr key={l.id}>
                <td>
                  <span className="font-medium tabular-nums">{l.code}</span>
                  {phone ? (
                    <span className="block text-xs break-all text-muted-foreground">
                      {l.affiliate_name} · {l.landing_path}
                    </span>
                  ) : null}
                </td>
                {phone ? null : (
                  <>
                    <td>{l.affiliate_name}</td>
                    <td className="break-all">{l.landing_path}</td>
                  </>
                )}
                <td className={figureCell}>{l.clicks}</td>
              </tr>
            ))}
          </TablePanel>
          <TablePanel
            caption={t("referrals.rulesTitle")}
            empty={!rules.data?.results.length && t("designS8.growth.noRules")}
            columns={[
              { header: t("referrals.name") },
              ...(phone ? [] : [{ header: t("referrals.ruleKind") }]),
              { header: t("designS8.growth.rate"), end: true },
              ...(phone ? [] : [{ header: t("referrals.months"), end: true }]),
            ]}
          >
            {rules.data?.results.map((r) => (
              <tr key={r.id}>
                <td>
                  <span className="font-medium">{r.name}</span>
                  {phone ? (
                    <span className="block text-xs text-muted-foreground">
                      {t(`referrals.ruleKinds.${r.kind ?? "percent"}`)} ·{" "}
                      {r.duration_months
                        ? `${t("referrals.months")}: ${r.duration_months}`
                        : t("referrals.lifetime")}
                    </span>
                  ) : null}
                </td>
                {phone ? null : <td>{t(`referrals.ruleKinds.${r.kind ?? "percent"}`)}</td>}
                <td className={figureCell}>
                  {r.kind === "bounty"
                    ? money(r.bounty, "en-GB")
                    : t("designS8.growth.percent", { value: r.percent })}
                </td>
                {phone ? null : (
                  <td className={figureCell}>{r.duration_months ?? t("referrals.lifetime")}</td>
                )}
              </tr>
            ))}
          </TablePanel>
        </>
      }
      side={
        canManage ? (
          <>
            <FormCard
              title={t("referrals.newAffiliate")}
              submit={t("referrals.addAffiliate")}
              pending={create.isPending}
              error={create.error}
              onSubmit={() => create.mutate()}
            >
              <TextField
                label={t("referrals.name")}
                required
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                error={errors.name}
              />
              <TextField
                label={t("referrals.email")}
                type="email"
                required
                value={form.email}
                onChange={(e) => setForm({ ...form, email: e.target.value })}
                error={errors.email}
              />
              <SelectField
                label={t("referrals.affiliateKind")}
                value={form.kind}
                onChange={(e) => setForm({ ...form, kind: e.target.value })}
                options={[
                  { value: "individual", label: t("referrals.affiliateKinds.individual") },
                  { value: "organisation", label: t("referrals.affiliateKinds.organisation") },
                ]}
              />
            </FormCard>
            {people.length ? (
              <FormCard
                title={t("referrals.newLink")}
                submit={t("referrals.addLink")}
                pending={addLink.isPending}
                error={addLink.error}
                onSubmit={() => addLink.mutate()}
              >
                <SelectField
                  label={t("referrals.affiliate")}
                  required
                  value={link.affiliate}
                  onChange={(e) => setLink({ ...link, affiliate: e.target.value })}
                  options={[
                    { value: "", label: t("referrals.choose") },
                    ...people.map((a) => ({ value: a.id, label: a.name })),
                  ]}
                />
                <TextField
                  label={t("referrals.linkName")}
                  value={link.name}
                  onChange={(e) => setLink({ ...link, name: e.target.value })}
                />
                <TextField
                  label={t("referrals.landingPath")}
                  value={link.landing_path}
                  onChange={(e) => setLink({ ...link, landing_path: e.target.value })}
                />
              </FormCard>
            ) : null}
            <FormCard
              title={t("referrals.newRule")}
              submit={t("referrals.addRule")}
              pending={saveRule.isPending}
              error={saveRule.error}
              onSubmit={() => saveRule.mutate()}
            >
              <TextField
                label={t("referrals.name")}
                required
                value={rule.name}
                onChange={(e) => setRule({ ...rule, name: e.target.value })}
              />
              <SelectField
                label={t("referrals.ruleKind")}
                value={rule.kind}
                onChange={(e) => setRule({ ...rule, kind: e.target.value })}
                options={[
                  { value: "percent", label: t("referrals.ruleKinds.percent") },
                  { value: "bounty", label: t("referrals.ruleKinds.bounty") },
                ]}
              />
              {rule.kind === "percent" ? (
                <TextField
                  label={t("referrals.rate")}
                  inputMode="decimal"
                  className="w-24 text-right"
                  value={rule.percent}
                  onChange={(e) => setRule({ ...rule, percent: e.target.value })}
                />
              ) : (
                <TextField
                  label={t("referrals.bounty")}
                  inputMode="decimal"
                  className="w-32 text-right"
                  value={rule.bounty}
                  onChange={(e) => setRule({ ...rule, bounty: e.target.value })}
                />
              )}
              <TextField
                label={t("referrals.months")}
                hint={t("referrals.monthsHint")}
                type="number"
                min={1}
                className="w-24 text-right"
                value={rule.months}
                onChange={(e) => setRule({ ...rule, months: e.target.value })}
              />
            </FormCard>
          </>
        ) : undefined
      }
    />
  );
}

function download(filename: string, content: string) {
  if (typeof URL.createObjectURL !== "function") return;
  const url = URL.createObjectURL(new Blob([content], { type: "text/plain" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function StatementsSection() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const canManage = usePermission("growth.commission.manage");
  const phone = useIsPhone();
  const [periodEnd, setPeriodEnd] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const statements = useQuery({
    queryKey: ["affiliate-statements"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/affiliate-statements", { params: { query: PAGE } })),
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["affiliate-statements"] });
  const issue = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/affiliate-statements/issue", {
          body: { period_end: periodEnd || null },
          headers: { "Idempotency-Key": `statements-${periodEnd || "last-month"}-${Date.now()}` },
        }),
      ),
    onSuccess: refresh,
  });
  const pay = useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.POST("/api/v1/affiliate-statements/{id}/pay", {
          params: { path: { id } },
          body: { reference: "" },
        }),
      ),
    onSuccess: refresh,
  });
  const bankFile = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/affiliate-statements/bank-file", {
          body: { statements: selected },
        }),
      ),
    onSuccess: (file) => download(file.filename, file.content),
  });
  const rows: Statement[] = statements.data?.results ?? [];
  return (
    <RecordLayout
      main={
        <>
          {issue.isSuccess ? (
            <Alert tone="success">{t("referrals.issued", { count: issue.data.length })}</Alert>
          ) : null}
          {pay.error ? <Alert tone="danger">{pay.error.message}</Alert> : null}
          {bankFile.error ? <Alert tone="danger">{bankFile.error.message}</Alert> : null}
          {statements.isPending ? (
            <Spinner label={t("grid.loading")} />
          ) : (
            <TablePanel
              caption={t("referrals.statementsTitle")}
              empty={!rows.length && t("referrals.noStatements")}
              footer={
                canManage && rows.length ? (
                  <>
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={!selected.length || bankFile.isPending}
                      onClick={() => bankFile.mutate()}
                    >
                      {t("referrals.bankFile")}
                    </Button>
                    <span className="text-muted-foreground" aria-live="polite">
                      {t("designS8.growth.chosen", { count: selected.length })}
                    </span>
                  </>
                ) : undefined
              }
              columns={[
                { header: t("referrals.select"), hidden: true, width: "w-10" },
                { header: t("referrals.number") },
                ...(phone ? [] : [{ header: t("referrals.period") }]),
                { header: t("referrals.total"), end: true, width: "w-32" },
                ...(phone
                  ? []
                  : [
                      { header: t("referrals.statusLabel") },
                      { header: t("referrals.actions"), hidden: true },
                    ]),
              ]}
            >
              {rows.map((s) => (
                <tr key={s.id}>
                  <td>
                    {s.status === "issued" ? (
                      <input
                        type="checkbox"
                        className="size-4"
                        aria-label={t("referrals.selectStatement", { number: s.number })}
                        checked={selected.includes(s.id)}
                        onChange={(e) =>
                          setSelected(
                            e.target.checked
                              ? [...selected, s.id]
                              : selected.filter((x) => x !== s.id),
                          )
                        }
                      />
                    ) : null}
                  </td>
                  <td>
                    <span className="font-medium tabular-nums">{s.number}</span>
                    <span className="block text-xs text-muted-foreground">
                      {phone
                        ? [
                            s.affiliate_name,
                            `${formatDate(s.period_start, i18n.language)} – ${formatDate(s.period_end, i18n.language)}`,
                            t(`referrals.statementStatus.${s.status}`),
                          ].join(" · ")
                        : s.affiliate_name}
                    </span>
                    {phone && canManage && s.status === "issued" ? (
                      <Button
                        size="sm"
                        variant="secondary"
                        className="mt-2"
                        onClick={() => pay.mutate(s.id)}
                      >
                        {t("referrals.markPaid")}
                      </Button>
                    ) : null}
                  </td>
                  {phone ? null : (
                    <td className="whitespace-nowrap tabular-nums">
                      {formatDate(s.period_start, i18n.language)} –{" "}
                      {formatDate(s.period_end, i18n.language)}
                    </td>
                  )}
                  <td className={figureCell}>{money(s.total, i18n.language)}</td>
                  {phone ? null : (
                    <>
                      <td>
                        {t(`referrals.statementStatus.${s.status}`)}
                        {s.paid_at ? (
                          <span className="block text-xs text-muted-foreground tabular-nums">
                            {formatDateTime(s.paid_at, i18n.language)}
                          </span>
                        ) : null}
                      </td>
                      <td className="text-right">
                        {canManage && s.status === "issued" ? (
                          <Button size="sm" variant="secondary" onClick={() => pay.mutate(s.id)}>
                            {t("referrals.markPaid")}
                          </Button>
                        ) : null}
                      </td>
                    </>
                  )}
                </tr>
              ))}
            </TablePanel>
          )}
        </>
      }
      side={
        canManage ? (
          <FormCard
            title={t("referrals.issueStatements")}
            submit={t("referrals.issue")}
            pending={issue.isPending}
            error={issue.error}
            onSubmit={() => issue.mutate()}
          >
            <TextField
              label={t("referrals.periodEnd")}
              hint={t("referrals.periodEndHint")}
              type="date"
              value={periodEnd}
              onChange={(e) => setPeriodEnd(e.target.value)}
            />
          </FormCard>
        ) : undefined
      }
    />
  );
}

// --- tutor referrals (T06) ----------------------------------------------------------------------

function TutorReferralsSection() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const canManage = usePermission("growth.tutor_referral.manage");
  const phone = useIsPhone();
  const rows = useQuery({
    queryKey: ["tutor-referrals"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/tutor-referrals", { params: { query: PAGE } })),
  });
  const act = useMutation({
    mutationFn: async ({ id, verb }: { id: string; verb: "pay" | "reject" }) =>
      verb === "pay"
        ? unwrap(
            await api.POST("/api/v1/tutor-referrals/{id}/pay", {
              params: { path: { id } },
              body: {},
            }),
          )
        : unwrap(
            await api.POST("/api/v1/tutor-referrals/{id}/reject", {
              params: { path: { id } },
              body: { reason: "" },
            }),
          ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["tutor-referrals"] }),
  });
  const list = rows.data?.results ?? [];
  return (
    <div className="space-y-4">
      {act.error ? <Alert tone="danger">{act.error.message}</Alert> : null}
      {rows.isPending ? (
        <Spinner label={t("grid.loading")} />
      ) : (
        <TablePanel
          caption={t("referrals.tutorTitle")}
          waiting={list.some((r) => r.status === "pending")}
          empty={!list.length && t("referrals.noTutorReferrals")}
          columns={[
            ...(phone ? [] : [{ header: t("referrals.referrer") }]),
            { header: t("referrals.referred") },
            ...(phone ? [] : [{ header: t("referrals.statusLabel") }]),
            { header: t("referrals.bonus"), end: true, width: "w-32" },
            ...(phone ? [] : [{ header: t("referrals.actions"), hidden: true }]),
          ]}
        >
          {list.map((r) => (
            <tr key={r.id}>
              {phone ? null : <td>{r.referrer_name}</td>}
              <td>
                {r.referred_name}
                <span className="block text-xs text-muted-foreground">
                  {phone ? `${t("referrals.referrer")} ${r.referrer_name} · ` : ""}
                  {t(`referrals.tutorKinds.${r.kind}`)} ·{" "}
                  <span className="tabular-nums">{formatDate(r.created_at, i18n.language)}</span>
                </span>
                {phone ? (
                  <span
                    className={`block ${r.status === "pending" ? "font-semibold text-margin" : ""}`}
                  >
                    {t(`referrals.tutorStatus.${r.status}`)}
                  </span>
                ) : null}
                {phone && canManage && r.status === "pending" ? (
                  <span className="mt-2 flex flex-wrap gap-1">
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => act.mutate({ id: r.id, verb: "pay" })}
                    >
                      {t("referrals.payBonus")}
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      className={ghost}
                      onClick={() => act.mutate({ id: r.id, verb: "reject" })}
                    >
                      {t("referrals.reject")}
                    </Button>
                  </span>
                ) : null}
              </td>
              {phone ? null : (
                <td>
                  <span
                    className={r.status === "pending" ? "font-semibold text-margin" : undefined}
                  >
                    {t(`referrals.tutorStatus.${r.status}`)}
                  </span>
                </td>
              )}
              <td className={figureCell}>{money(r.bonus, i18n.language)}</td>
              {phone ? null : (
                <td className="text-right">
                  {canManage && r.status === "pending" ? (
                    <div className="flex flex-wrap justify-end gap-1">
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => act.mutate({ id: r.id, verb: "pay" })}
                      >
                        {t("referrals.payBonus")}
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        className={ghost}
                        onClick={() => act.mutate({ id: r.id, verb: "reject" })}
                      >
                        {t("referrals.reject")}
                      </Button>
                    </div>
                  ) : null}
                </td>
              )}
            </tr>
          ))}
        </TablePanel>
      )}
    </div>
  );
}

// --- settings -----------------------------------------------------------------------------------

function SettingsSection() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canManage = usePermission("org.settings.manage");
  const area = useQuery({
    queryKey: ["settings", "growth"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/settings/{area}", { params: { path: { area: "growth" } } })),
  });
  const [values, setValues] = useState<Record<string, unknown>>({});
  useEffect(() => {
    if (area.data) setValues(area.data.values);
  }, [area.data]);
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PATCH("/api/v1/settings/{area}", {
          params: { path: { area: "growth" } },
          body: { values },
        }),
      ),
    onSuccess: (data) => queryClient.setQueryData(["settings", "growth"], data),
  });
  const errors = fieldErrors(save.error);
  if (!area.data) return <Spinner label={t("grid.loading")} />;
  return (
    <Panel title={t("referrals.settings")} flush className="max-w-2xl">
      <form
        aria-label={t("referrals.settings")}
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <div className="space-y-4 px-5 py-4">
          {area.data.schema.map((d) => {
            const value = values[d.key];
            if (d.type === "bool") {
              return (
                <label key={d.key} className="flex items-start gap-2 text-sm">
                  <input
                    type="checkbox"
                    className="mt-0.5 size-4"
                    disabled={!canManage}
                    checked={Boolean(value)}
                    onChange={(e) => setValues({ ...values, [d.key]: e.target.checked })}
                  />
                  {d.label}
                </label>
              );
            }
            if (d.type === "choice") {
              return (
                <SelectField
                  key={d.key}
                  label={d.label}
                  disabled={!canManage}
                  value={String(value ?? "")}
                  onChange={(e) => setValues({ ...values, [d.key]: e.target.value })}
                  options={(d.choices ?? []).map((c) => ({
                    value: String(c.value),
                    label: String(c.label),
                  }))}
                />
              );
            }
            return (
              <TextField
                key={d.key}
                label={d.label}
                disabled={!canManage}
                type={d.type === "int" ? "number" : "text"}
                className={d.type === "int" ? "w-24 text-right" : undefined}
                min={d.min_value}
                max={d.max_value}
                value={String(value ?? "")}
                error={errors[d.key]}
                onChange={(e) =>
                  setValues({
                    ...values,
                    [d.key]: d.type === "int" ? Number(e.target.value) : e.target.value,
                  })
                }
              />
            );
          })}
          {save.error ? <Alert tone="danger">{save.error.message}</Alert> : null}
        </div>
        {canManage ? (
          <PanelFooter>
            <Button type="submit" size="sm" loading={save.isPending}>
              {t("referrals.saveSettings")}
            </Button>
            {save.isSuccess ? (
              <span role="status" className="text-muted-foreground">
                {t("referrals.saved")}
              </span>
            ) : null}
          </PanelFooter>
        ) : null}
      </form>
    </Panel>
  );
}

// --- the public review page (T01, T02) ----------------------------------------------------------

/** The page behind the review request email: stars, optional criteria, a comment and
 * permission to publish. 4-5 star reviewers are invited to review on Google too. */
export function ReviewPage({ token }: { token: string }) {
  const { t } = useTranslation();
  const [rating, setRating] = useState(0);
  const [criteria, setCriteria] = useState<Record<string, number>>({});
  const [text, setText] = useState("");
  const [name, setName] = useState<string | null>(null);
  const [consent, setConsent] = useState(false);
  const page = useQuery({
    queryKey: ["public-review", token],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/public/review/{token}", { params: { path: { token } } })),
    retry: false,
  });
  const submit = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/public/review/{token}", {
          params: { path: { token } },
          body: {
            rating,
            criteria,
            text,
            reviewer_name: name ?? page.data?.reviewer_name ?? "",
            publish_consent: consent,
          },
        }),
      ),
  });
  if (page.isError) return <PublicLayout title={t("reviews.page.missing")}>{null}</PublicLayout>;
  if (!page.data) return <PublicLayout loading />;
  const p = page.data;
  const title = p.tutor
    ? t("reviews.page.titleTutor", { tutor: p.tutor })
    : t("reviews.page.title", { organisation: p.organisation });
  if (submit.isSuccess) {
    return (
      <PublicLayout title={t("reviews.page.thanks")}>
        <p role="status">{t("reviews.page.thanksBody")}</p>
        {submit.data.google_review_url ? (
          <p className="mt-4">
            <a
              className="text-link underline-offset-2 hover:underline"
              href={submit.data.google_review_url}
              rel="noopener noreferrer"
            >
              {t("reviews.page.google")}
            </a>
          </p>
        ) : null}
      </PublicLayout>
    );
  }
  if (!p.open) {
    return (
      <PublicLayout title={title}>
        <p role="status">{t("reviews.page.closed")}</p>
      </PublicLayout>
    );
  }
  return (
    <PublicLayout title={title} wide>
      <form
        className="rounded-xl border border-border bg-surface"
        aria-label={title}
        onSubmit={(e) => {
          e.preventDefault();
          if (rating) submit.mutate();
        }}
      >
        <div className="space-y-6 px-5 py-4">
          <StarChoice
            legend={t("reviews.page.overall")}
            value={rating}
            onChange={setRating}
            required
          />
          {p.criteria.map((c) => (
            <StarChoice
              key={c}
              legend={t(`reviews.criteria.${c}`, { defaultValue: c.replace(/_/g, " ") })}
              value={criteria[c] ?? 0}
              onChange={(n) => setCriteria({ ...criteria, [c]: n })}
            />
          ))}
          <TextAreaField
            id="review-text"
            label={t("reviews.page.comment")}
            rows={4}
            maxLength={5000}
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <TextField
            label={t("reviews.page.name")}
            hint={t("reviews.page.nameHint")}
            value={name ?? p.reviewer_name}
            onChange={(e) => setName(e.target.value)}
          />
          <CheckboxField
            label={t("reviews.page.consent", { organisation: p.organisation })}
            checked={consent}
            onChange={(e) => setConsent(e.target.checked)}
          />
          {submit.error ? <Alert tone="danger">{submit.error.message}</Alert> : null}
        </div>
        <PanelFooter>
          <Button type="submit" disabled={!rating} loading={submit.isPending}>
            {t("reviews.page.submit")}
          </Button>
        </PanelFooter>
      </form>
    </PublicLayout>
  );
}

/** A 1-5 star radio group: five field-edged tiles, each a drawn star over its number; the
 * chosen tile takes the wash and an ink edge (keyboard: arrow keys move between stars). */
function StarChoice({
  legend,
  value,
  onChange,
  required = false,
}: {
  legend: string;
  value: number;
  onChange: (n: number) => void;
  required?: boolean;
}) {
  const { t } = useTranslation();
  return (
    <fieldset>
      <legend className="text-sm font-medium">{legend}</legend>
      <div className="mt-2 grid max-w-sm grid-cols-5 gap-2">
        {[1, 2, 3, 4, 5].map((n) => (
          <label
            key={n}
            className="flex cursor-pointer flex-col items-center gap-1 rounded-md border border-field bg-surface px-1 py-2 hover:bg-muted has-[:checked]:border-foreground has-[:checked]:bg-muted has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-link"
          >
            <input
              type="radio"
              className="sr-only"
              name={legend}
              aria-label={t("reviews.stars", { count: n })}
              value={n}
              required={required}
              checked={value === n}
              onChange={() => onChange(n)}
            />
            <Star
              aria-hidden="true"
              strokeWidth={1.75}
              className={n <= value ? "size-5 fill-current text-foreground" : "size-5 text-field"}
            />
            <span aria-hidden="true" className="text-xs tabular-nums">
              {n}
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}
