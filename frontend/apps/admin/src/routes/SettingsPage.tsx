import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  FormPanel,
  NamePlate,
  PageHeader,
  PanelRow,
  PanelRows,
  RuledPanel,
  SelectField,
  TextField,
  UnitField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api, fieldErrors, useFeature, useOrganisation, type Term } from "../api";
import { ProcessTimeline } from "../components/ProcessTimeline";
import { SavedNote } from "../components/SavedNote";
import { Locked } from "../subscription/UpgradePrompts";
import { SupportAccessSection } from "./SupportAccessSection";

const TERMS = ["tutor", "student", "client", "lesson", "job"] as const;
const BUSINESS_TYPES = ["sole_trader", "team", "agency", "centre", "online"] as const;

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
        business_type: org.business_type ?? "sole_trader",
      });
    }
  }, [org]);
  const save = useMutation({
    mutationFn: async () => unwrap(await api.PATCH("/api/v1/organisation", { body: form })),
    onSuccess: (data) => {
      queryClient.setQueryData(["organisation"], data);
      // The type of business decides which menus show (sole traders see fewer).
      void queryClient.invalidateQueries({ queryKey: ["me"] });
    },
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
  return (
    <FormPanel
      title={t("settings.profile")}
      submit={t("common.save")}
      pending={save.isPending}
      onSubmit={() => save.mutate()}
      error={
        save.isError && !Object.keys(errors).length ? (
          <Alert tone="danger">{save.error.message}</Alert>
        ) : null
      }
      trail={<SavedNote show={save.isSuccess} />}
    >
      {field("name", t("settings.name"))}
      {field("legal_name", t("settings.legalName"))}
      {field("slug", t("settings.subdomain"), { hint: t("settings.subdomainHint") })}
      {field("timezone", t("settings.timezone"))}
      {field("contact_email", t("settings.contactEmail"), { type: "email" })}
      {field("contact_phone", t("settings.contactPhone"), { type: "tel" })}
      {field("primary_colour", t("settings.primaryColour"), {
        type: "color",
        className: "w-24 cursor-pointer px-1",
        hint: t("designS9b.settings.colourHint"),
      })}
      <div className="sm:col-span-2">
        <SelectField
          label={t("settings.businessType")}
          hint={t("settings.businessTypeHint")}
          value={form.business_type ?? "sole_trader"}
          error={errors.business_type}
          onChange={(e) => setForm((f) => ({ ...f, business_type: e.target.value }))}
          options={BUSINESS_TYPES.map((b) => ({ value: b, label: t(`businessTypes.${b}`) }))}
        />
      </div>
    </FormPanel>
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
  return (
    <FormPanel
      title={t("settings.general")}
      submit={t("common.save")}
      pending={save.isPending}
      onSubmit={() => save.mutate()}
      error={
        save.isError && !Object.keys(errors).length ? (
          <Alert tone="danger">{save.error.message}</Alert>
        ) : null
      }
      trail={<SavedNote show={save.isSuccess} />}
    >
      <div className="sm:col-span-2">
        <UnitField
          label={t("settings.lessonDuration")}
          min={1}
          value={duration}
          error={errors["general.default_lesson_duration"]}
          onChange={(e) => setDuration(e.target.value)}
        />
      </div>
      <fieldset className="grid gap-x-4 gap-y-3 border-t border-rule pt-3 sm:col-span-2 sm:grid-cols-2">
        <legend className="float-left w-full text-sm font-semibold">
          {t("settings.terminology")}
        </legend>
        <p className="-mt-2 text-xs text-muted-foreground sm:col-span-2">
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
    </FormPanel>
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
  const rows = branches.data?.results ?? [];
  return (
    <RuledPanel
      flush
      title={t("settings.branches")}
      aside={
        branches.data ? (
          <span className="text-muted-foreground tabular-nums">
            {t("designS9b.settings.branchCount", { count: rows.length })}
          </span>
        ) : null
      }
    >
      <PanelRows>
        {rows.map((b) => (
          <PanelRow key={b.id}>
            <NamePlate
              name={b.name}
              context={[b.code, b.is_default ? t("settings.default") : ""]
                .filter(Boolean)
                .join(" · ")}
              aside={
                !b.is_default ? (
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-muted-foreground"
                    onClick={() => archive.mutate(b.id)}
                  >
                    {t("settings.archive")}
                  </Button>
                ) : null
              }
            />
          </PanelRow>
        ))}
      </PanelRows>
      <div className="border-t border-rule px-5 py-4">
        <Locked feature="multi_branch">
          <form
            className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_8rem_auto] sm:items-end"
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
            <Button type="submit" variant="secondary" loading={create.isPending}>
              {t("settings.addBranch")}
            </Button>
          </form>
        </Locked>
      </div>
    </RuledPanel>
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
    <RuledPanel
      title={t("settings.demo")}
      description={t("settings.demoBody")}
      footer={
        <Button
          variant="secondary"
          size="sm"
          loading={wipe.isPending}
          onClick={() => wipe.mutate()}
        >
          {t("settings.wipeDemo")}
        </Button>
      }
      flush
    />
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
      <RuledPanel title={t("settings.close")}>
        <Alert tone="info">{t("settings.closed")}</Alert>
      </RuledPanel>
    );
  }
  return (
    <form
      aria-labelledby="close-account-title"
      onSubmit={(e) => {
        e.preventDefault();
        close.mutate();
      }}
    >
      <RuledPanel
        flush
        titleId="close-account-title"
        title={t("settings.close")}
        description={t("settings.closeBody")}
        footer={
          <Button
            type="submit"
            variant="danger"
            disabled={form.confirm_slug !== slug || !form.password}
            loading={close.isPending}
          >
            {t("settings.closeAction")}
          </Button>
        }
      >
        <div className="grid gap-x-4 gap-y-3 px-5 py-4 sm:grid-cols-2">
          {close.isError && Object.keys(errors).length === 0 ? (
            <Alert tone="danger" className="sm:col-span-2">
              {close.error.message}
            </Alert>
          ) : null}
          <div className="sm:col-span-2">
            <TextField
              label={t("settings.closeReason")}
              value={form.reason}
              onChange={(e) => setForm((f) => ({ ...f, reason: e.target.value }))}
            />
          </div>
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
        </div>
      </RuledPanel>
    </form>
  );
}

export function SettingsPage() {
  const { t } = useTranslation();
  const { data: org } = useOrganisation();
  const multiBranch = useFeature("multi_branch");
  return (
    <div className="max-w-3xl">
      <PageHeader title={t("settings.title")} description={t("designS9b.settings.description")} />
      <div className="space-y-6">
        <ProfileSection />
        <GeneralSection />
        {multiBranch ? <BranchesSection /> : null}
        {org?.has_demo_data ? <DemoDataSection /> : null}
        <SupportAccessSection />
        {org ? <ProcessTimeline subjectType="organisation" subjectId={org.id} /> : null}
        {org ? <CloseAccountSection slug={org.slug} /> : null}
      </div>
    </div>
  );
}
