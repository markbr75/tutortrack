import { unwrap, type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  buttonClass,
  CheckboxField,
  NamePlate,
  Panel,
  PanelRow,
  PanelRows,
  RuledPanel,
  Segmented,
  SelectField,
  Spinner,
  TextAreaField,
  TextField,
} from "@tutortrack/ui";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";

import { api, fieldErrors, useOrganisation, usePermission } from "../api";
import { RecordHeader } from "../components/RecordHeader";
import { SavedNote } from "../components/SavedNote";
import { isHex } from "../website/contrast";
import { ColourField, ImageField } from "../website/fields";
import { useBrandColour, useInvoiceTemplates } from "./invoiceTemplateHooks";
import { PanelEmpty, PanelLoading } from "./moneyUi";

type Template = components["schemas"]["InvoiceTemplate"];
type Draft = components["schemas"]["InvoiceTemplateRequest"];
type Style = NonNullable<Draft["style"]>;
type LogoMode = NonNullable<Draft["logo_mode"]>;

const STYLES: readonly Style[] = ["classic", "modern", "compact"];
const LOGOS: readonly LogoMode[] = ["brand", "own", "none"];
const COLUMNS = [
  "show_date",
  "show_student",
  "show_tutor",
  "show_quantity",
  "show_unit_price",
] as const;

const BLANK: Draft = {
  name: "",
  is_default: false,
  style: "classic",
  accent_colour: "",
  logo_mode: "brand",
  logo: null,
  title: "",
  trading_name: "",
  intro: "",
  payment_instructions: "",
  footer: "",
  show_date: true,
  show_student: true,
  show_tutor: true,
  show_quantity: true,
  show_unit_price: true,
};

function toDraft(template: Template): Draft {
  return Object.fromEntries(
    Object.keys(BLANK).map((key) => [
      key,
      template[key as keyof Template] ?? BLANK[key as keyof Draft],
    ]),
  ) as Draft;
}

/** What the preview may draw: a colour mid-typing is left out rather than refused. */
function previewBody(draft: Draft): Draft {
  return {
    ...draft,
    accent_colour: draft.accent_colour && isHex(draft.accent_colour) ? draft.accent_colour : "",
    logo_mode: draft.logo_mode === "own" && !draft.logo ? "none" : draft.logo_mode,
  };
}

/** Billing › Invoice templates (ADR 0046): the organisation's templates, the default first. */
export function InvoiceTemplatesList() {
  const { t } = useTranslation();
  const canManage = usePermission("billing.template.manage");
  const list = useInvoiceTemplates();
  const rows = list.data ?? [];
  return (
    <Panel
      title={t("invoiceTemplates.title")}
      flush
      aside={
        canManage ? (
          <Link
            className={buttonClass({ size: "sm" })}
            to="/billing/templates/$templateId"
            params={{ templateId: "new" }}
          >
            {t("invoiceTemplates.new")}
          </Link>
        ) : null
      }
    >
      <p className="border-b border-rule px-5 py-3 text-sm text-muted-foreground">
        {t("invoiceTemplates.intro")}
      </p>
      {list.isPending ? (
        <PanelLoading label={t("grid.loading")} />
      ) : rows.length ? (
        <PanelRows>
          {rows.map((template) => (
            <PanelRow key={template.id}>
              <NamePlate
                name={
                  <Link
                    className="font-medium underline-offset-2 hover:underline"
                    to="/billing/templates/$templateId"
                    params={{ templateId: template.id }}
                  >
                    {template.name}
                  </Link>
                }
                context={[
                  t(`invoiceTemplates.styles.${template.style ?? "classic"}`),
                  template.is_default ? t("invoiceTemplates.isDefault") : "",
                ]
                  .filter(Boolean)
                  .join(" · ")}
              />
            </PanelRow>
          ))}
        </PanelRows>
      ) : (
        <PanelEmpty>{t("invoiceTemplates.none")}</PanelEmpty>
      )}
    </Panel>
  );
}

/** /billing/templates: the list as its own page (where the editor's way back leads). */
export function InvoiceTemplatesPage() {
  const { t } = useTranslation();
  return (
    <article>
      <RecordHeader
        back={<Link to="/billing">{t("billing.title")}</Link>}
        title={t("invoiceTemplates.title")}
      />
      <InvoiceTemplatesList />
    </article>
  );
}

/** /billing/templates/$templateId ("new" to add one): the editor with its live preview. */
export function InvoiceTemplatePage({ templateId }: { templateId: string }) {
  const { t } = useTranslation();
  const isNew = templateId === "new";
  const existing = useQuery({
    queryKey: ["invoice-templates", templateId],
    enabled: !isNew,
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/invoice-templates/{id}", { params: { path: { id: templateId } } }),
      ),
  });
  if (!isNew && !existing.data) {
    return existing.isError ? (
      <Alert tone="danger">{t("errors.generic")}</Alert>
    ) : (
      <Spinner label={t("grid.loading")} />
    );
  }
  return (
    <TemplateEditor
      key={templateId}
      templateId={isNew ? null : templateId}
      initial={existing.data ? toDraft(existing.data) : BLANK}
    />
  );
}

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(value), ms);
    return () => window.clearTimeout(id);
  }, [value, ms]);
  return debounced;
}

function TemplateEditor({ templateId, initial }: { templateId: string | null; initial: Draft }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { data: org } = useOrganisation();
  const canManage = usePermission("billing.template.manage");
  const brandColour = useBrandColour();
  const [form, setForm] = useState<Draft>(initial);
  const [saved, setSaved] = useState(false);
  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => {
    setSaved(false);
    setForm((current) => ({ ...current, [key]: value }));
  };

  const save = useMutation({
    mutationFn: async () =>
      templateId
        ? unwrap(
            await api.PATCH("/api/v1/invoice-templates/{id}", {
              params: { path: { id: templateId } },
              body: form,
            }),
          )
        : unwrap(await api.POST("/api/v1/invoice-templates", { body: form })),
    onSuccess: (template) => {
      void queryClient.invalidateQueries({ queryKey: ["invoice-templates"] });
      setSaved(true);
      if (!templateId) {
        void navigate({
          to: "/billing/templates/$templateId",
          params: { templateId: template.id },
        });
      }
    },
  });
  const errors = fieldErrors(save.error);

  const shown = useDebounced(form, 400);
  const preview = useQuery({
    queryKey: ["invoice-template-preview", shown],
    placeholderData: keepPreviousData,
    queryFn: async () =>
      unwrap(await api.POST("/api/v1/invoice-templates/preview", { body: previewBody(shown) }))
        .html,
  });
  const sample = useMutation({
    mutationFn: async () => {
      const result = await api.POST("/api/v1/invoice-templates/preview-pdf", {
        body: previewBody(form),
        parseAs: "blob",
      });
      const response = result.response as Response;
      if (!response.ok || !result.data) throw new Error(t("invoiceTemplates.sampleFailed"));
      const url = URL.createObjectURL(result.data as unknown as Blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "sample-invoice.pdf";
      link.click();
      URL.revokeObjectURL(url);
    },
  });

  const title = form.name || (templateId ? "" : t("invoiceTemplates.newTitle"));
  return (
    <article>
      <RecordHeader
        back={<Link to="/billing/templates">{t("invoiceTemplates.title")}</Link>}
        title={title}
        description={form.is_default ? t("invoiceTemplates.isDefault") : undefined}
        actions={
          <Button
            size="sm"
            variant="secondary"
            loading={sample.isPending}
            onClick={() => sample.mutate()}
          >
            {t("invoiceTemplates.samplePdf")}
          </Button>
        }
      />
      {sample.error ? <Alert tone="danger">{sample.error.message}</Alert> : null}
      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,26rem)_minmax(0,1fr)]">
        <form
          aria-label={t("invoiceTemplates.editorLabel")}
          className="space-y-6"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <fieldset disabled={!canManage} className="min-w-0 space-y-6">
            <RuledPanel title={t("invoiceTemplates.sections.template")}>
              <div className="space-y-3">
                <TextField
                  label={t("invoiceTemplates.name")}
                  hint={t("invoiceTemplates.nameHint")}
                  required
                  value={form.name}
                  error={errors.name}
                  onChange={(e) => set("name", e.target.value)}
                />
                <CheckboxField
                  label={t("invoiceTemplates.makeDefault")}
                  hint={t("invoiceTemplates.makeDefaultHint")}
                  checked={Boolean(form.is_default)}
                  onChange={(e) => set("is_default", e.target.checked)}
                />
              </div>
            </RuledPanel>

            <RuledPanel title={t("invoiceTemplates.sections.look")}>
              <div className="space-y-4">
                <div className="space-y-1.5">
                  <p className="text-sm font-medium" aria-hidden="true">
                    {t("invoiceTemplates.style")}
                  </p>
                  <Segmented
                    label={t("invoiceTemplates.style")}
                    fill
                    options={STYLES.map((key) => ({
                      key,
                      label: t(`invoiceTemplates.styles.${key}`),
                    }))}
                    value={form.style ?? "classic"}
                    onChange={(key) => set("style", key)}
                  />
                  <p className="text-xs text-muted-foreground">
                    {t(`invoiceTemplates.styleHints.${form.style ?? "classic"}`)}
                  </p>
                </div>
                <div className="space-y-1">
                  <ColourField
                    label={t("invoiceTemplates.accent")}
                    value={form.accent_colour ?? ""}
                    fallback={brandColour}
                    error={errors.accent_colour}
                    onChange={(value) => set("accent_colour", value)}
                  />
                  <p className="text-xs text-muted-foreground">
                    {t("invoiceTemplates.accentHint")}
                  </p>
                  {form.accent_colour ? (
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      className="-ml-3 text-muted-foreground"
                      onClick={() => set("accent_colour", "")}
                    >
                      {t("invoiceTemplates.useBrandColour")}
                    </Button>
                  ) : null}
                </div>
                <SelectField
                  label={t("invoiceTemplates.logo")}
                  value={form.logo_mode ?? "brand"}
                  error={errors.logo_mode}
                  options={LOGOS.map((key) => ({
                    value: key,
                    label: t(`invoiceTemplates.logos.${key}`),
                  }))}
                  onChange={(e) => set("logo_mode", e.target.value as LogoMode)}
                />
                {form.logo_mode === "own" ? (
                  <div className="space-y-1">
                    <ImageField
                      label={t("invoiceTemplates.ownLogo")}
                      current={form.logo}
                      onUploaded={(id) => set("logo", id)}
                    />
                    {errors.logo ? (
                      <p className="text-xs text-danger" role="alert">
                        {errors.logo}
                      </p>
                    ) : null}
                  </div>
                ) : null}
              </div>
            </RuledPanel>

            <RuledPanel title={t("invoiceTemplates.sections.wording")}>
              <div className="space-y-3">
                <TextField
                  label={t("invoiceTemplates.titleField")}
                  hint={t("invoiceTemplates.titleHint")}
                  placeholder={t("invoiceTemplates.defaultTitle")}
                  value={form.title ?? ""}
                  error={errors.title}
                  onChange={(e) => set("title", e.target.value)}
                />
                <TextField
                  label={t("invoiceTemplates.tradingName")}
                  hint={t("invoiceTemplates.tradingNameHint")}
                  placeholder={org?.name}
                  value={form.trading_name ?? ""}
                  error={errors.trading_name}
                  onChange={(e) => set("trading_name", e.target.value)}
                />
                <TextAreaField
                  label={t("invoiceTemplates.introField")}
                  hint={t("invoiceTemplates.introHint")}
                  value={form.intro ?? ""}
                  onChange={(e) => set("intro", e.target.value)}
                />
                <TextAreaField
                  label={t("invoiceTemplates.howToPay")}
                  hint={t("invoiceTemplates.fallbackHint")}
                  value={form.payment_instructions ?? ""}
                  onChange={(e) => set("payment_instructions", e.target.value)}
                />
                <TextAreaField
                  label={t("invoiceTemplates.footer")}
                  hint={t("invoiceTemplates.fallbackHint")}
                  value={form.footer ?? ""}
                  onChange={(e) => set("footer", e.target.value)}
                />
              </div>
            </RuledPanel>

            <RuledPanel
              title={t("invoiceTemplates.sections.columns")}
              description={t("invoiceTemplates.columnsHint")}
            >
              <div className="space-y-2">
                {COLUMNS.map((key) => (
                  <CheckboxField
                    key={key}
                    label={t(`invoiceTemplates.columns.${key}`)}
                    checked={Boolean(form[key])}
                    onChange={(e) => set(key, e.target.checked)}
                  />
                ))}
              </div>
            </RuledPanel>
          </fieldset>

          {canManage ? (
            <div className="sticky bottom-0 z-10 -mx-1 border-t border-rule bg-background/95 px-1 py-3 backdrop-blur">
              <div className="flex flex-wrap items-center gap-3">
                <Button type="submit" loading={save.isPending}>
                  {templateId ? t("common.save") : t("invoiceTemplates.create")}
                </Button>
                <SavedNote show={saved && !save.isPending} />
                {templateId && !form.is_default ? <DeleteTemplate templateId={templateId} /> : null}
              </div>
              {save.error && !Object.keys(errors).length ? (
                <Alert tone="danger" className="mt-2">
                  {save.error.message}
                </Alert>
              ) : null}
            </div>
          ) : null}
        </form>

        <section
          aria-labelledby="invoice-preview-h"
          className="space-y-2 lg:sticky lg:top-[4.5rem]"
        >
          <div className="flex items-baseline justify-between gap-3">
            <h2 id="invoice-preview-h" className="text-base font-semibold">
              {t("invoiceTemplates.preview")}
            </h2>
            {preview.isFetching ? (
              <span role="status" className="text-xs text-muted-foreground">
                {t("invoiceTemplates.updating")}
              </span>
            ) : null}
          </div>
          <p className="text-xs text-muted-foreground">{t("invoiceTemplates.previewHint")}</p>
          {preview.data ? (
            <iframe
              title={t("invoiceTemplates.previewFrame")}
              // No scripts, forms or navigation: the preview is a picture of the invoice.
              sandbox=""
              srcDoc={preview.data}
              className="h-[75vh] w-full rounded-xl border border-border bg-white"
            />
          ) : preview.isError ? (
            <Alert tone="danger">{t("invoiceTemplates.previewFailed")}</Alert>
          ) : (
            <Spinner label={t("grid.loading")} />
          )}
        </section>
      </div>
    </article>
  );
}

/** Delete, confirmed in place (never a browser prompt); families and jobs that used the
 * template go back to the default. */
function DeleteTemplate({ templateId }: { templateId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [confirming, setConfirming] = useState(false);
  const confirmButton = useRef<HTMLButtonElement>(null);
  const openButton = useRef<HTMLButtonElement>(null);
  const opened = useRef(false);
  useEffect(() => {
    if (confirming) confirmButton.current?.focus();
    else if (opened.current) openButton.current?.focus();
    opened.current = confirming;
  }, [confirming]);
  const remove = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.DELETE("/api/v1/invoice-templates/{id}", {
          params: { path: { id: templateId } },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["invoice-templates"] });
      void navigate({ to: "/billing/templates" });
    },
  });
  if (!confirming) {
    return (
      <Button
        ref={openButton}
        type="button"
        variant="ghost"
        className="ml-auto text-muted-foreground"
        onClick={() => setConfirming(true)}
      >
        {t("invoiceTemplates.delete")}
      </Button>
    );
  }
  return (
    <div
      role="group"
      aria-labelledby="delete-template-confirm"
      className="flex basis-full flex-wrap items-center gap-2"
      onKeyDown={(e) => {
        if (e.key === "Escape") setConfirming(false);
      }}
    >
      <p id="delete-template-confirm" className="basis-full text-sm">
        {t("invoiceTemplates.deleteConfirm")}
      </p>
      <Button
        ref={confirmButton}
        type="button"
        variant="danger"
        size="sm"
        loading={remove.isPending}
        onClick={() => remove.mutate()}
      >
        {t("invoiceTemplates.delete")}
      </Button>
      <Button
        type="button"
        size="sm"
        variant="ghost"
        className="text-muted-foreground"
        onClick={() => setConfirming(false)}
      >
        {t("common.cancel")}
      </Button>
      {remove.error ? <Alert tone="danger">{remove.error.message}</Alert> : null}
    </div>
  );
}
