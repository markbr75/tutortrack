import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, Button, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";

import { api, fieldErrors, useFeature, useOrganisation, type Term } from "../api";
import { ProcessTimeline } from "../components/ProcessTimeline";
import { Locked } from "../subscription/UpgradePrompts";

const TERMS = ["tutor", "student", "client", "lesson", "job"] as const;

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mt-8 max-w-2xl rounded-md border border-border p-4 md:p-6">
      <h2 className="text-lg font-medium">{title}</h2>
      <div className="mt-4">{children}</div>
    </section>
  );
}

function ProfileSection() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { data: org } = useOrganisation();
  const [form, setForm] = useState<Record<string, string>>({});
  useEffect(() => {
    if (org) {
      setForm({
        name: org.name,
        legal_name: org.legal_name ?? "",
        slug: org.slug,
        contact_email: org.contact_email ?? "",
        contact_phone: org.contact_phone ?? "",
        timezone: org.timezone ?? "",
        primary_colour: org.primary_colour || "#2563eb",
      });
    }
  }, [org]);
  const save = useMutation({
    mutationFn: async () => unwrap(await api.PATCH("/api/v1/organisation", { body: form })),
    onSuccess: (data) => queryClient.setQueryData(["organisation"], data),
  });
  const errors = fieldErrors(save.error);
  const field = (name: string, label: string, extra: Record<string, unknown> = {}) => (
    <TextField
      label={label}
      value={form[name] ?? ""}
      error={errors[name]}
      onChange={(e) => setForm((f) => ({ ...f, [name]: e.target.value }))}
      {...extra}
    />
  );
  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }
  return (
    <Section title={t("settings.profile")}>
      <form onSubmit={submit} className="grid gap-4 sm:grid-cols-2">
        {field("name", t("settings.name"))}
        {field("legal_name", t("settings.legalName"))}
        {field("slug", t("settings.subdomain"), { hint: t("settings.subdomainHint") })}
        {field("timezone", t("settings.timezone"))}
        {field("contact_email", t("settings.contactEmail"), { type: "email" })}
        {field("contact_phone", t("settings.contactPhone"), { type: "tel" })}
        {field("primary_colour", t("settings.primaryColour"), { type: "color" })}
        <div className="flex items-end gap-3 sm:col-span-2">
          <Button type="submit" loading={save.isPending}>
            {t("common.save")}
          </Button>
          {save.isSuccess ? <span role="status">{t("common.saved")}</span> : null}
        </div>
      </form>
    </Section>
  );
}

function GeneralSection() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const general = useQuery({
    queryKey: ["settings", "general"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/settings/{area}", { params: { path: { area: "general" } } })),
  });
  const [duration, setDuration] = useState("60");
  const [terms, setTerms] = useState<Record<string, Term>>({});
  useEffect(() => {
    const values = general.data?.values;
    if (!values) return;
    setDuration(String(values["general.default_lesson_duration"]));
    setTerms(values["general.terminology"] as Record<string, Term>);
  }, [general.data]);
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PATCH("/api/v1/settings/{area}", {
          params: { path: { area: "general" } },
          body: {
            values: {
              "general.default_lesson_duration": Number(duration),
              "general.terminology": terms,
            },
          },
        }),
      ),
    onSuccess: (data) => queryClient.setQueryData(["settings", "general"], data),
  });
  const errors = fieldErrors(save.error);
  function submit(event: FormEvent) {
    event.preventDefault();
    save.mutate();
  }
  return (
    <Section title={t("settings.general")}>
      <form onSubmit={submit} className="flex flex-col gap-4">
        <TextField
          label={t("settings.lessonDuration")}
          type="number"
          value={duration}
          error={errors["general.default_lesson_duration"]}
          onChange={(e) => setDuration(e.target.value)}
        />
        <fieldset className="grid gap-3 sm:grid-cols-2">
          <legend className="mb-2 text-sm font-medium">{t("settings.terminology")}</legend>
          <p className="text-xs text-muted-foreground sm:col-span-2">
            {t("settings.terminologyHint")}
          </p>
          {TERMS.map((term) =>
            (["singular", "plural"] as const).map((form) => (
              <TextField
                key={`${term}-${form}`}
                label={t(`settings.${form}`, { term: t(`terms.${term}`) })}
                value={terms[term]?.[form] ?? ""}
                onChange={(e) =>
                  setTerms((all) => ({
                    ...all,
                    [term]: {
                      ...(all[term] ?? { singular: "", plural: "" }),
                      [form]: e.target.value,
                    },
                  }))
                }
              />
            )),
          )}
          {errors["general.terminology"] ? (
            <p className="text-xs text-danger sm:col-span-2" role="alert">
              {errors["general.terminology"]}
            </p>
          ) : null}
        </fieldset>
        <div className="flex items-center gap-3">
          <Button type="submit" loading={save.isPending}>
            {t("common.save")}
          </Button>
          {save.isSuccess ? <span role="status">{t("common.saved")}</span> : null}
        </div>
      </form>
    </Section>
  );
}

function BranchesSection() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const branches = useQuery({
    queryKey: ["branches"],
    queryFn: async () => unwrap(await api.GET("/api/v1/branches")),
  });
  const [form, setForm] = useState({ name: "", code: "" });
  const create = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/branches", { body: form })),
    onSuccess: () => {
      setForm({ name: "", code: "" });
      void queryClient.invalidateQueries({ queryKey: ["branches"] });
    },
  });
  const archive = useMutation({
    mutationFn: async (id: string) =>
      unwrap(await api.DELETE("/api/v1/branches/{id}", { params: { path: { id } } })),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["branches"] }),
  });
  const errors = fieldErrors(create.error);
  return (
    <Section title={t("settings.branches")}>
      <ul className="divide-y divide-border">
        {branches.data?.results.map((b) => (
          <li key={b.id} className="flex items-center justify-between py-2 text-sm">
            <span>
              {b.name} <span className="text-muted-foreground">({b.code})</span>
              {b.is_default ? ` · ${t("settings.default")}` : ""}
            </span>
            {!b.is_default ? (
              <Button size="sm" variant="ghost" onClick={() => archive.mutate(b.id)}>
                {t("settings.archive")}
              </Button>
            ) : null}
          </li>
        ))}
      </ul>
      <Locked feature="multi_branch">
        <form
          className="mt-4 grid gap-3 sm:grid-cols-[1fr_8rem_auto] sm:items-end"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <TextField
            label={t("settings.branchName")}
            value={form.name}
            error={errors.name}
            onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
          />
          <TextField
            label={t("settings.branchCode")}
            value={form.code}
            error={errors.code}
            onChange={(e) => setForm((f) => ({ ...f, code: e.target.value }))}
          />
          <Button type="submit" loading={create.isPending}>
            {t("settings.addBranch")}
          </Button>
        </form>
      </Locked>
    </Section>
  );
}

function DemoDataSection() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const wipe = useMutation({
    mutationFn: async () => unwrap(await api.DELETE("/api/v1/demo-data")),
    onSuccess: () => void queryClient.invalidateQueries(),
  });
  return (
    <Section title={t("settings.demo")}>
      <p className="text-sm">{t("settings.demoBody")}</p>
      <Button
        className="mt-3"
        variant="secondary"
        loading={wipe.isPending}
        onClick={() => wipe.mutate()}
      >
        {t("settings.wipeDemo")}
      </Button>
    </Section>
  );
}

function CloseAccountSection({ slug }: { slug: string }) {
  const { t } = useTranslation();
  const [form, setForm] = useState({ password: "", confirm_slug: "", reason: "" });
  const close = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/organisation/close", { body: { ...form, export_data: true } }),
      ),
  });
  const errors = fieldErrors(close.error);
  if (close.isSuccess) {
    return (
      <Section title={t("settings.close")}>
        <Alert tone="info">{t("settings.closed")}</Alert>
      </Section>
    );
  }
  return (
    <Section title={t("settings.close")}>
      <p className="text-sm">{t("settings.closeBody")}</p>
      <form
        className="mt-4 flex flex-col gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          close.mutate();
        }}
      >
        {close.isError && Object.keys(errors).length === 0 ? (
          <Alert tone="danger">{close.error.message}</Alert>
        ) : null}
        <TextField
          label={t("settings.closeReason")}
          value={form.reason}
          onChange={(e) => setForm((f) => ({ ...f, reason: e.target.value }))}
        />
        <TextField
          label={t("settings.closeConfirmSlug", { slug })}
          value={form.confirm_slug}
          error={errors.confirm_slug}
          onChange={(e) => setForm((f) => ({ ...f, confirm_slug: e.target.value }))}
        />
        <TextField
          label={t("settings.closePassword")}
          type="password"
          autoComplete="current-password"
          value={form.password}
          error={errors.password}
          onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))}
        />
        <Button
          type="submit"
          variant="danger"
          disabled={form.confirm_slug !== slug || !form.password}
          loading={close.isPending}
        >
          {t("settings.closeAction")}
        </Button>
      </form>
    </Section>
  );
}

export function SettingsPage() {
  const { t } = useTranslation();
  const { data: org } = useOrganisation();
  const multiBranch = useFeature("multi_branch");
  return (
    <div>
      <h1 className="text-2xl font-semibold">{t("settings.title")}</h1>
      <ProfileSection />
      <GeneralSection />
      {multiBranch ? <BranchesSection /> : null}
      {org?.has_demo_data ? <DemoDataSection /> : null}
      {org ? <ProcessTimeline subjectType="organisation" subjectId={org.id} /> : null}
      {org ? <CloseAccountSection slug={org.slug} /> : null}
    </div>
  );
}
