import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatDateTime, formatMoney, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, Tabs, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";

import { api, fieldErrors, useOrganisation, usePermission } from "../api";
import { PublicLayout } from "../layout/PublicLayout";

type Review = components["schemas"]["Review"];
type Referral = components["schemas"]["Referral"];
type Program = components["schemas"]["ReferralProgram"];
type Affiliate = components["schemas"]["Affiliate"];
type Statement = components["schemas"]["AffiliateStatement"];
type MoneyValue = { amount: string; currency: string };

const PAGE = { page_size: 200 };

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

/** Stars shown visually, with the rating as text for screen readers. */
export function Stars({ rating }: { rating: number }) {
  const { t } = useTranslation();
  return (
    <span>
      <span aria-hidden="true" className="text-warning">
        {"★".repeat(rating)}
        {"☆".repeat(Math.max(0, 5 - rating))}
      </span>
      <span className="sr-only">{t("reviews.stars", { count: rating })}</span>
    </span>
  );
}

function money(value: MoneyValue | null | undefined, locale: string): string {
  return value ? formatMoney(value, locale) : "—";
}

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
      <h1 className="mb-4 text-2xl font-semibold">{t("referrals.title")}</h1>
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
  return (
    <div className="space-y-4">
      {summary.data ? (
        <p role="status">
          {summary.data.average === null
            ? t("reviews.noRatings")
            : t("reviews.summary", {
                average: summary.data.average.toLocaleString(i18n.language),
                count: summary.data.count,
              })}
        </p>
      ) : null}
      <div className="max-w-xs">
        <SelectField
          label={t("reviews.filter")}
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
      {reviews.isPending ? <Spinner label={t("grid.loading")} /> : null}
      {reviews.data && !reviews.data.results.length ? <p>{t("reviews.empty")}</p> : null}
      {reviews.data?.results.length ? (
        <Table
          caption={t("reviews.listTitle")}
          headers={[
            t("reviews.rating"),
            t("reviews.review"),
            t("reviews.tutor"),
            t("reviews.status.label"),
            t("referrals.actions"),
          ]}
        >
          {reviews.data.results.map((r) => (
            <tr key={r.id}>
              <Cell>
                <Stars rating={r.rating} />
              </Cell>
              <Cell>
                <p>{r.text || t("reviews.noComment")}</p>
                <p className="text-xs text-muted-foreground">
                  {r.reviewer_name} · {r.client_name} · {formatDate(r.created_at, i18n.language)}
                </p>
                {r.response ? (
                  <p className="mt-1 text-xs">
                    {t("reviews.ourReply")}: {r.response}
                  </p>
                ) : null}
                {replying === r.id ? (
                  <form
                    className="mt-2 flex flex-wrap items-end gap-2"
                    aria-label={t("reviews.reply")}
                    onSubmit={(e) => {
                      e.preventDefault();
                      respond.mutate(r.id);
                    }}
                  >
                    <TextField
                      label={t("reviews.reply")}
                      value={reply}
                      onChange={(e) => setReply(e.target.value)}
                    />
                    <Button type="submit" disabled={respond.isPending}>
                      {t("reviews.sendReply")}
                    </Button>
                  </form>
                ) : null}
              </Cell>
              <Cell>{r.tutor_name || t("reviews.business")}</Cell>
              <Cell>
                {t(`reviews.status.${r.status}`)}
                {r.published_as_testimonial ? (
                  <span className="block text-xs">{t("reviews.onWebsite")}</span>
                ) : null}
              </Cell>
              <Cell>
                {canManage ? (
                  <div className="flex flex-wrap gap-1">
                    {r.status !== "approved" ? (
                      <Button size="sm" onClick={() => act.mutate({ id: r.id, verb: "approve" })}>
                        {t("reviews.approve")}
                      </Button>
                    ) : null}
                    {r.status !== "hidden" ? (
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => act.mutate({ id: r.id, verb: "hide" })}
                      >
                        {t("reviews.hide")}
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
                      variant="secondary"
                      onClick={() => {
                        setReplying(r.id);
                        setReply(r.response);
                      }}
                    >
                      {t("reviews.reply")}
                    </Button>
                  </div>
                ) : null}
              </Cell>
            </tr>
          ))}
        </Table>
      ) : null}
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
  return (
    <div className="space-y-4">
      {canManage ? (
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
              ...(clients.data?.results ?? []).map((c) => ({ value: c.id, label: c.display_name })),
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
      ) : null}
      {requests.data?.results.length ? (
        <Table
          caption={t("reviews.requestsTitle")}
          headers={[
            t("reviews.client"),
            t("reviews.tutor"),
            t("reviews.trigger.label"),
            t("reviews.status.label"),
            t("reviews.expires"),
            t("referrals.actions"),
          ]}
        >
          {requests.data.results.map((r) => (
            <tr key={r.id}>
              <Cell>{r.client_name}</Cell>
              <Cell>{r.tutor_name || t("reviews.business")}</Cell>
              <Cell>{t(`reviews.trigger.${r.trigger}`)}</Cell>
              <Cell>{t(`reviews.requestStatus.${r.status}`)}</Cell>
              <Cell>{formatDate(r.expires_at, i18n.language)}</Cell>
              <Cell>
                {canManage && (r.status === "pending" || r.status === "reminded") ? (
                  <Button size="sm" variant="secondary" onClick={() => cancel.mutate(r.id)}>
                    {t("referrals.cancel")}
                  </Button>
                ) : null}
              </Cell>
            </tr>
          ))}
        </Table>
      ) : (
        <p>{t("reviews.noRequests")}</p>
      )}
    </div>
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
          value={form.lessons}
          onChange={(e) => set("lessons")(e.target.value)}
        />
      ) : null}
      <TextField
        label={t("referrals.discount")}
        hint={t("referrals.discountHint")}
        inputMode="decimal"
        value={form.discount}
        onChange={(e) => set("discount")(e.target.value)}
        error={errors.referee_discount_percent}
      />
      <TextField
        label={t("referrals.deadline")}
        type="number"
        min={1}
        value={form.deadline}
        onChange={(e) => set("deadline")(e.target.value)}
      />
      <TextField
        label={t("referrals.limit")}
        hint={t("referrals.limitHint")}
        type="number"
        min={1}
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
  return (
    <div className="space-y-4">
      {canManage && programs.data ? (
        <ProgramForm
          key={program?.id ?? "new"}
          program={program}
          currency={org?.default_currency ?? "GBP"}
        />
      ) : null}
      {act.error ? <Alert tone="danger">{act.error.message}</Alert> : null}
      {referrals.data?.results.length ? (
        <Table
          caption={t("referrals.listTitle")}
          headers={[
            t("referrals.referrer"),
            t("referrals.referee"),
            t("referrals.statusLabel"),
            t("referrals.rewardLabel"),
            t("referrals.actions"),
          ]}
        >
          {referrals.data.results.map((r: Referral) => (
            <tr key={r.id}>
              <Cell>{r.referrer_name}</Cell>
              <Cell>
                {r.referee_name}
                <span className="block text-xs text-muted-foreground">
                  {formatDate(r.created_at, i18n.language)}
                </span>
              </Cell>
              <Cell>
                {t(`referrals.status.${r.status}`)}
                {Array.isArray(r.fraud_flags) && r.fraud_flags.length ? (
                  <span className="block text-xs text-danger">
                    {(r.fraud_flags as string[]).map((f) => t(`referrals.flags.${f}`)).join(", ")}
                  </span>
                ) : null}
              </Cell>
              <Cell>{money(r.referrer_credit, i18n.language)}</Cell>
              <Cell>
                {canManage ? (
                  <div className="flex flex-wrap gap-1">
                    {r.status === "blocked" ? (
                      <Button size="sm" onClick={() => act.mutate({ id: r.id, verb: "approve" })}>
                        {t("referrals.approve")}
                      </Button>
                    ) : null}
                    {["pending", "converted", "blocked"].includes(r.status) ? (
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => act.mutate({ id: r.id, verb: "cancel" })}
                      >
                        {t("referrals.cancel")}
                      </Button>
                    ) : null}
                  </div>
                ) : null}
              </Cell>
            </tr>
          ))}
        </Table>
      ) : (
        <p>{t("referrals.empty")}</p>
      )}
    </div>
  );
}

// --- affiliates (T04, T05) ----------------------------------------------------------------------

function AffiliatesSection() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canManage = usePermission("growth.affiliate.manage");
  const [form, setForm] = useState({ name: "", email: "", kind: "individual" });
  const [link, setLink] = useState({ affiliate: "", name: "", landing_path: "/" });
  const affiliates = useQuery({
    queryKey: ["affiliates"],
    queryFn: async () => unwrap(await api.GET("/api/v1/affiliates", { params: { query: PAGE } })),
  });
  const links = useQuery({
    queryKey: ["affiliate-links"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/affiliate-links", { params: { query: PAGE } })),
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
  const errors = fieldErrors(create.error);
  return (
    <div className="space-y-4">
      {canManage ? (
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
      ) : null}
      {invite.isSuccess ? (
        <p role="status">{t("referrals.invited", { email: invite.data.email })}</p>
      ) : null}
      {invite.error ? <Alert tone="danger">{invite.error.message}</Alert> : null}
      {affiliates.data?.results.length ? (
        <Table
          caption={t("referrals.affiliatesTitle")}
          headers={[
            t("referrals.name"),
            t("referrals.email"),
            t("referrals.statusLabel"),
            t("referrals.payout"),
            t("referrals.actions"),
          ]}
        >
          {affiliates.data.results.map((a) => (
            <tr key={a.id}>
              <Cell>{a.name}</Cell>
              <Cell>{a.email}</Cell>
              <Cell>{t(`referrals.affiliateStatus.${a.status ?? "active"}`)}</Cell>
              <Cell>
                {t(`referrals.payoutMethods.${a.payout_method ?? "manual"}`)} {a.bank_hint}
              </Cell>
              <Cell>
                {canManage && !a.has_login ? (
                  <Button size="sm" variant="secondary" onClick={() => invite.mutate(a.id)}>
                    {t("referrals.invite")}
                  </Button>
                ) : a.has_login ? (
                  t("referrals.hasLogin")
                ) : null}
              </Cell>
            </tr>
          ))}
        </Table>
      ) : (
        <p>{t("referrals.noAffiliates")}</p>
      )}
      {canManage && affiliates.data?.results.length ? (
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
              ...affiliates.data.results.map((a) => ({ value: a.id, label: a.name })),
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
      {links.data?.results.length ? (
        <Table
          caption={t("referrals.linksTitle")}
          headers={[
            t("referrals.code"),
            t("referrals.affiliate"),
            t("referrals.landingPath"),
            t("referrals.clicks"),
          ]}
        >
          {links.data.results.map((l) => (
            <tr key={l.id}>
              <Cell>
                <code>{l.code}</code>
              </Cell>
              <Cell>{l.affiliate_name}</Cell>
              <Cell>{l.landing_path}</Cell>
              <Cell>{l.clicks}</Cell>
            </tr>
          ))}
        </Table>
      ) : null}
      <RulesSection />
    </div>
  );
}

function RulesSection() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canManage = usePermission("growth.affiliate.manage");
  const { data: org } = useOrganisation();
  const [form, setForm] = useState({
    name: "",
    kind: "percent",
    percent: "10",
    bounty: "",
    months: "12",
  });
  const rules = useQuery({
    queryKey: ["commission-rules"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/commission-rules", { params: { query: PAGE } })),
  });
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/commission-rules", {
          body: {
            name: form.name,
            kind: form.kind as "percent" | "bounty",
            percent: form.kind === "percent" ? form.percent : null,
            bounty:
              form.kind === "bounty"
                ? { amount: form.bounty, currency: org?.default_currency ?? "GBP" }
                : null,
            duration_months: form.months ? Number(form.months) : null,
          },
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["commission-rules"] }),
  });
  return (
    <div className="space-y-3">
      {rules.data?.results.length ? (
        <Table
          caption={t("referrals.rulesTitle")}
          headers={[
            t("referrals.name"),
            t("referrals.ruleKind"),
            t("referrals.rate"),
            t("referrals.months"),
          ]}
        >
          {rules.data.results.map((r) => (
            <tr key={r.id}>
              <Cell>{r.name}</Cell>
              <Cell>{t(`referrals.ruleKinds.${r.kind ?? "percent"}`)}</Cell>
              <Cell>{r.kind === "bounty" ? money(r.bounty, "en-GB") : `${r.percent}%`}</Cell>
              <Cell>{r.duration_months ?? t("referrals.lifetime")}</Cell>
            </tr>
          ))}
        </Table>
      ) : null}
      {canManage ? (
        <FormCard
          title={t("referrals.newRule")}
          submit={t("referrals.addRule")}
          pending={save.isPending}
          error={save.error}
          onSubmit={() => save.mutate()}
        >
          <TextField
            label={t("referrals.name")}
            required
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
          <SelectField
            label={t("referrals.ruleKind")}
            value={form.kind}
            onChange={(e) => setForm({ ...form, kind: e.target.value })}
            options={[
              { value: "percent", label: t("referrals.ruleKinds.percent") },
              { value: "bounty", label: t("referrals.ruleKinds.bounty") },
            ]}
          />
          {form.kind === "percent" ? (
            <TextField
              label={t("referrals.rate")}
              inputMode="decimal"
              value={form.percent}
              onChange={(e) => setForm({ ...form, percent: e.target.value })}
            />
          ) : (
            <TextField
              label={t("referrals.bounty")}
              inputMode="decimal"
              value={form.bounty}
              onChange={(e) => setForm({ ...form, bounty: e.target.value })}
            />
          )}
          <TextField
            label={t("referrals.months")}
            hint={t("referrals.monthsHint")}
            type="number"
            min={1}
            value={form.months}
            onChange={(e) => setForm({ ...form, months: e.target.value })}
          />
        </FormCard>
      ) : null}
    </div>
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
    <div className="space-y-4">
      {canManage ? (
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
      ) : null}
      {issue.isSuccess ? (
        <p role="status">{t("referrals.issued", { count: issue.data.length })}</p>
      ) : null}
      {pay.error ? <Alert tone="danger">{pay.error.message}</Alert> : null}
      {bankFile.error ? <Alert tone="danger">{bankFile.error.message}</Alert> : null}
      {rows.length ? (
        <>
          <Table
            caption={t("referrals.statementsTitle")}
            headers={[
              t("referrals.select"),
              t("referrals.number"),
              t("referrals.affiliate"),
              t("referrals.period"),
              t("referrals.total"),
              t("referrals.statusLabel"),
              t("referrals.actions"),
            ]}
          >
            {rows.map((s) => (
              <tr key={s.id}>
                <Cell>
                  {s.status === "issued" ? (
                    <input
                      type="checkbox"
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
                </Cell>
                <Cell>{s.number}</Cell>
                <Cell>{s.affiliate_name}</Cell>
                <Cell>
                  {formatDate(s.period_start, i18n.language)} –{" "}
                  {formatDate(s.period_end, i18n.language)}
                </Cell>
                <Cell>{money(s.total, i18n.language)}</Cell>
                <Cell>
                  {t(`referrals.statementStatus.${s.status}`)}
                  {s.paid_at ? (
                    <span className="block text-xs">
                      {formatDateTime(s.paid_at, i18n.language)}
                    </span>
                  ) : null}
                </Cell>
                <Cell>
                  {canManage && s.status === "issued" ? (
                    <Button size="sm" variant="secondary" onClick={() => pay.mutate(s.id)}>
                      {t("referrals.markPaid")}
                    </Button>
                  ) : null}
                </Cell>
              </tr>
            ))}
          </Table>
          {canManage ? (
            <Button
              variant="secondary"
              disabled={!selected.length || bankFile.isPending}
              onClick={() => bankFile.mutate()}
            >
              {t("referrals.bankFile")}
            </Button>
          ) : null}
        </>
      ) : (
        <p>{t("referrals.noStatements")}</p>
      )}
    </div>
  );
}

// --- tutor referrals (T06) ----------------------------------------------------------------------

function TutorReferralsSection() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const canManage = usePermission("growth.tutor_referral.manage");
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
  return (
    <div className="space-y-4">
      {act.error ? <Alert tone="danger">{act.error.message}</Alert> : null}
      {rows.data?.results.length ? (
        <Table
          caption={t("referrals.tutorTitle")}
          headers={[
            t("referrals.referrer"),
            t("referrals.tutorKind"),
            t("referrals.referred"),
            t("referrals.statusLabel"),
            t("referrals.bonus"),
            t("referrals.actions"),
          ]}
        >
          {rows.data.results.map((r) => (
            <tr key={r.id}>
              <Cell>{r.referrer_name}</Cell>
              <Cell>{t(`referrals.tutorKinds.${r.kind}`)}</Cell>
              <Cell>
                {r.referred_name}
                <span className="block text-xs text-muted-foreground">
                  {formatDate(r.created_at, i18n.language)}
                </span>
              </Cell>
              <Cell>{t(`referrals.tutorStatus.${r.status}`)}</Cell>
              <Cell>{money(r.bonus, i18n.language)}</Cell>
              <Cell>
                {canManage && r.status === "pending" ? (
                  <div className="flex flex-wrap gap-1">
                    <Button size="sm" onClick={() => act.mutate({ id: r.id, verb: "pay" })}>
                      {t("referrals.payBonus")}
                    </Button>
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => act.mutate({ id: r.id, verb: "reject" })}
                    >
                      {t("referrals.reject")}
                    </Button>
                  </div>
                ) : null}
              </Cell>
            </tr>
          ))}
        </Table>
      ) : (
        <p>{t("referrals.noTutorReferrals")}</p>
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
    <form
      className="max-w-2xl space-y-3"
      aria-label={t("referrals.settings")}
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      {area.data.schema.map((d) => {
        const value = values[d.key];
        if (d.type === "bool") {
          return (
            <label key={d.key} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
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
      {save.isSuccess ? <p role="status">{t("referrals.saved")}</p> : null}
      {canManage ? (
        <Button type="submit" disabled={save.isPending}>
          {t("referrals.saveSettings")}
        </Button>
      ) : null}
    </form>
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
  if (!page.data) return <Spinner label={t("grid.loading")} />;
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
            <a className="underline" href={submit.data.google_review_url} rel="noopener noreferrer">
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
        className="space-y-4"
        aria-label={title}
        onSubmit={(e) => {
          e.preventDefault();
          if (rating) submit.mutate();
        }}
      >
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
        <div className="flex flex-col gap-1">
          <label htmlFor="review-text" className="text-sm font-medium">
            {t("reviews.page.comment")}
          </label>
          <textarea
            id="review-text"
            className="min-h-28 rounded-md border border-border bg-background p-3 text-sm"
            maxLength={5000}
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
        </div>
        <TextField
          label={t("reviews.page.name")}
          hint={t("reviews.page.nameHint")}
          value={name ?? p.reviewer_name}
          onChange={(e) => setName(e.target.value)}
        />
        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            className="mt-1"
            checked={consent}
            onChange={(e) => setConsent(e.target.checked)}
          />
          {t("reviews.page.consent", { organisation: p.organisation })}
        </label>
        {submit.error ? <Alert tone="danger">{submit.error.message}</Alert> : null}
        <Button type="submit" disabled={!rating || submit.isPending}>
          {t("reviews.page.submit")}
        </Button>
      </form>
    </PublicLayout>
  );
}

/** A 1-5 star radio group (keyboard: arrow keys move between stars). */
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
      <div className="mt-1 flex gap-1">
        {[1, 2, 3, 4, 5].map((n) => (
          <label
            key={n}
            className="flex size-11 cursor-pointer items-center justify-center rounded-md text-2xl focus-within:ring-2 focus-within:ring-primary"
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
            <span
              aria-hidden="true"
              className={n <= value ? "text-warning" : "text-muted-foreground"}
            >
              {n <= value ? "★" : "☆"}
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}
