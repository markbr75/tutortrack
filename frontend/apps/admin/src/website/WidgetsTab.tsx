import { unwrap, type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  NamePlate,
  PanelFooter,
  PanelRow,
  PanelRows,
  RuledPanel,
  SelectField,
  Spinner,
  TextField,
} from "@tutortrack/ui";
import { Check, Copy } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { api, usePermission } from "../api";
import { errorText, fieldErrors, useBrandingOptions } from "./helpers";
import { Card } from "./shared";

type Widget = components["schemas"]["Widget"];
type Options = Record<string, unknown>;

function CopyBlock({ label, value }: { label: string; value: string }) {
  const { t } = useTranslation();
  const id = useId();
  const [copied, setCopied] = useState(false);
  return (
    <div className="space-y-1.5">
      <p id={id} className="text-sm font-medium">
        {label}
      </p>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start">
        <pre
          aria-labelledby={id}
          className="min-w-0 flex-1 rounded-md border border-field bg-background px-3 py-2 text-xs break-all whitespace-pre-wrap"
        >
          {value}
        </pre>
        <Button
          size="sm"
          variant="secondary"
          className="shrink-0"
          onClick={() => {
            void navigator.clipboard?.writeText(value);
            setCopied(true);
          }}
        >
          {copied ? (
            <Check aria-hidden="true" className="size-4" strokeWidth={1.75} />
          ) : (
            <Copy aria-hidden="true" className="size-4" strokeWidth={1.75} />
          )}
          {copied ? t("website.copied") : t("website.copyNamed", { what: label })}
        </Button>
      </div>
    </div>
  );
}

/** Kind-specific settings for the widget builder. */
function OptionsEditor({
  kind,
  value,
  onChange,
}: {
  kind: string;
  value: Options;
  onChange: (next: Options) => void;
}) {
  const { t } = useTranslation();
  const forms = useQuery({
    queryKey: ["forms"],
    queryFn: async () => unwrap(await api.GET("/api/v1/forms")),
    enabled: kind === "enquiry_form" || kind === "tutor_directory",
  });
  const services = useQuery({
    queryKey: ["catalogue-services-all"],
    queryFn: async () => {
      const rows = unwrap(await api.GET("/api/v1/catalogue/services"));
      return Array.isArray(rows) ? rows : rows.results;
    },
    enabled: kind === "services",
  });
  const set = (key: string, v: unknown) => onChange({ ...value, [key]: v });
  const formOptions = [
    { value: "", label: t("website.widgets.chooseForm") },
    ...(forms.data ?? []).filter((f) => f.published).map((f) => ({ value: f.slug, label: f.name })),
  ];
  if (kind === "enquiry_form") {
    return (
      <SelectField
        label={t("website.widgets.form")}
        value={String(value.form ?? "")}
        onChange={(e) => set("form", e.target.value)}
        options={formOptions}
      />
    );
  }
  if (kind === "tutor_directory") {
    return (
      <div className="grid gap-3 sm:grid-cols-2">
        <TextField
          label={t("website.widgets.subjects")}
          hint={t("website.widgets.subjectsHint")}
          value={((value.subjects as string[] | undefined) ?? []).join(", ")}
          onChange={(e) =>
            set(
              "subjects",
              e.target.value
                .split(",")
                .map((s) => s.trim())
                .filter(Boolean),
            )
          }
        />
        <TextField
          label={t("website.widgets.pageSize")}
          type="number"
          min={3}
          max={48}
          value={String(value.page_size ?? 12)}
          onChange={(e) => set("page_size", Number(e.target.value))}
        />
        <SelectField
          label={t("website.widgets.enquiryForm")}
          value={String(value.enquiry_form ?? "")}
          onChange={(e) => set("enquiry_form", e.target.value)}
          options={formOptions}
        />
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            className="size-4"
            checked={value.show_filters !== false}
            onChange={(e) => set("show_filters", e.target.checked)}
          />
          {t("website.widgets.showFilters")}
        </label>
      </div>
    );
  }
  if (kind === "services") {
    const chosen = (value.services as string[] | undefined) ?? [];
    return (
      <div className="space-y-2">
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            className="size-4"
            checked={Boolean(value.show_prices)}
            onChange={(e) => set("show_prices", e.target.checked)}
          />
          {t("website.widgets.showPrices")}
        </label>
        <fieldset className="space-y-1">
          <legend className="text-sm font-medium">{t("website.widgets.services")}</legend>
          <p className="text-xs text-muted-foreground">{t("website.widgets.servicesHint")}</p>
          {(services.data ?? []).map((s) => (
            <label key={s.id} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="size-4"
                checked={chosen.includes(s.id)}
                onChange={(e) =>
                  set(
                    "services",
                    e.target.checked ? [...chosen, s.id] : chosen.filter((x) => x !== s.id),
                  )
                }
              />
              {s.name}
            </label>
          ))}
        </fieldset>
      </div>
    );
  }
  if (kind === "class_catalogue") {
    return (
      <div className="grid gap-3 sm:grid-cols-2">
        <TextField
          label={t("courses.widgetSubject")}
          value={String(value.subject ?? "")}
          onChange={(e) => set("subject", e.target.value)}
        />
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            className="size-4"
            checked={value.show_prices !== false}
            onChange={(e) => set("show_prices", e.target.checked)}
          />
          {t("website.widgets.showPrices")}
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            className="size-4"
            checked={value.show_filters !== false}
            onChange={(e) => set("show_filters", e.target.checked)}
          />
          {t("website.widgets.showFilters")}
        </label>
      </div>
    );
  }
  if (kind === "reviews") {
    return (
      <div className="grid gap-3 sm:grid-cols-2">
        <TextField
          label={t("website.widgets.limit")}
          type="number"
          min={1}
          max={24}
          value={String(value.limit ?? 6)}
          onChange={(e) => set("limit", Number(e.target.value))}
        />
        <SelectField
          label={t("website.widgets.minRating")}
          value={String(value.min_rating ?? "")}
          onChange={(e) => set("min_rating", e.target.value ? Number(e.target.value) : undefined)}
          options={[
            { value: "", label: t("website.widgets.anyRating") },
            ...["3", "4", "5"].map((n) => ({ value: n, label: n })),
          ]}
        />
      </div>
    );
  }
  if (kind === "login") {
    return (
      <div className="grid gap-3 sm:grid-cols-2">
        <SelectField
          label={t("website.widgets.portal")}
          value={String(value.portal ?? "client")}
          onChange={(e) => set("portal", e.target.value)}
          options={[
            { value: "client", label: t("website.widgets.portalClient") },
            { value: "tutor", label: t("website.widgets.portalTutor") },
            { value: "staff", label: t("website.widgets.portalStaff") },
          ]}
        />
        <TextField
          label={t("website.widgets.buttonText")}
          value={String(value.button_text ?? "")}
          onChange={(e) => set("button_text", e.target.value)}
        />
      </div>
    );
  }
  return null;
}

function originsFrom(text: string): string[] {
  return text
    .split(/[\s,]+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

/** A sandboxed live preview: the real widget script against this organisation's API. */
function WidgetPreview({ widget, scriptUrl }: { widget: Widget; scriptUrl: string }) {
  const { t } = useTranslation();
  const origin = window.location.origin;
  const attrs =
    widget.kind === "enquiry_form" ? ` form="${String(widget.options.form ?? "")}"` : "";
  const doc = `<!doctype html><html lang="${document.documentElement.lang || "en-GB"}"><body style="margin:12px">
<script type="module" src="${scriptUrl}" data-org="" data-api="${origin}"></script>
<${widget.element} widget="${widget.key}"${attrs}></${widget.element}></body></html>`;
  return (
    <iframe
      title={t("website.widgets.previewOf", { name: widget.name })}
      sandbox="allow-scripts allow-same-origin allow-forms"
      srcDoc={doc}
      className="block h-80 w-full rounded-md border border-border bg-white"
    />
  );
}

export function WidgetsTab() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canManage = usePermission("sites.widget.manage");
  const options = useBrandingOptions();
  const kinds = useQuery({
    queryKey: ["widget-kinds"],
    queryFn: async () => unwrap(await api.GET("/api/v1/widgets/kinds")),
  });
  const widgets = useQuery({
    queryKey: ["widgets"],
    queryFn: async () => unwrap(await api.GET("/api/v1/widgets")),
  });
  const [kind, setKind] = useState("tutor_directory");
  const [name, setName] = useState("");
  const [opts, setOpts] = useState<Options>({});
  const [origins, setOrigins] = useState("");
  const [radius, setRadius] = useState("");
  const [previewing, setPreviewing] = useState<string | null>(null);
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["widgets"] });
  const create = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/widgets", {
          body: {
            kind,
            name,
            options: opts as Record<string, never>,
            theme: radius ? { "--tt-radius": radius } : {},
            allowed_origins: originsFrom(origins),
          },
        }),
      ),
    onSuccess: (widget) => {
      setName("");
      setOpts({});
      setOrigins("");
      setPreviewing(widget.id);
      refresh();
    },
  });
  const update = useMutation({
    mutationFn: async ({ id, body }: { id: string; body: Record<string, unknown> }) =>
      unwrap(
        await api.PATCH("/api/v1/widgets/{id}", { params: { path: { id } }, body: body as never }),
      ),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: async (id: string) =>
      unwrap(await api.DELETE("/api/v1/widgets/{id}", { params: { path: { id } } })),
    onSuccess: refresh,
  });
  if (!kinds.data || !widgets.data || !options.data) return <Spinner label={t("grid.loading")} />;
  const errors = fieldErrors(create.error);
  const available = kinds.data.filter((k) => k.available);
  const description = kinds.data.find((k) => k.key === kind)?.description;
  return (
    <div className="max-w-4xl space-y-6">
      <p className="text-sm text-muted-foreground">{t("website.widgets.intro")}</p>
      {widgets.data.results.length === 0 ? (
        <p className="rounded-xl border border-border bg-surface px-5 py-6 text-sm text-muted-foreground">
          {t("website.widgets.none")}
        </p>
      ) : null}
      {widgets.data.results.map((widget) => (
        <Card
          key={widget.id}
          title={widget.name}
          description={
            <>
              {kinds.data.find((k) => k.key === widget.kind)?.title} ·{" "}
              <span className="tabular-nums">{widget.key}</span>
              {!widget.active ? (
                <span className="font-medium text-foreground">
                  {" · "}
                  {t("website.widgets.inactive")}
                </span>
              ) : null}
            </>
          }
          footer={
            <>
              <Button
                size="sm"
                variant="secondary"
                aria-expanded={previewing === widget.id}
                onClick={() => setPreviewing(previewing === widget.id ? null : widget.id)}
              >
                {previewing === widget.id
                  ? t("website.widgets.hidePreview")
                  : t("website.widgets.preview")}
              </Button>
              {canManage ? (
                <>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      const next = window.prompt(
                        t("website.widgets.originsPrompt"),
                        widget.allowed_origins.join(", "),
                      );
                      if (next !== null)
                        update.mutate({
                          id: widget.id,
                          body: { allowed_origins: originsFrom(next) },
                        });
                    }}
                  >
                    {t("website.widgets.editOrigins")}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() =>
                      update.mutate({ id: widget.id, body: { active: !widget.active } })
                    }
                  >
                    {widget.active
                      ? t("website.widgets.deactivate")
                      : t("website.widgets.activate")}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-muted-foreground"
                    aria-label={t("website.removeNamed", { name: widget.name })}
                    onClick={() => remove.mutate(widget.id)}
                  >
                    {t("website.remove")}
                  </Button>
                </>
              ) : null}
            </>
          }
        >
          <CopyBlock label={t("website.widgets.embed")} value={widget.embed_code} />
          <CopyBlock label={t("website.widgets.shortcode")} value={widget.wordpress_shortcode} />
          <p className="text-sm">
            <span className="text-muted-foreground">{t("website.widgets.allowed")}:</span>{" "}
            <span className="break-all">
              {widget.allowed_origins.length
                ? widget.allowed_origins.join(", ")
                : t("website.widgets.allowedNone")}
            </span>
          </p>
          {previewing === widget.id ? (
            <WidgetPreview widget={widget} scriptUrl={options.data.widgets_script_url} />
          ) : null}
        </Card>
      ))}
      {canManage ? (
        <RuledPanel title={t("website.widgets.new")} flush>
          <form
            aria-label={t("website.widgets.new")}
            onSubmit={(e) => {
              e.preventDefault();
              create.mutate();
            }}
          >
            <div className="space-y-4 px-5 py-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <SelectField
                  label={t("website.widgets.kind")}
                  value={kind}
                  hint={description}
                  onChange={(e) => {
                    setKind(e.target.value);
                    setOpts({});
                  }}
                  options={available.map((k) => ({ value: k.key, label: k.title }))}
                />
                <TextField
                  label={t("website.widgets.name")}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </div>
              <OptionsEditor kind={kind} value={opts} onChange={setOpts} />
              <div className="grid gap-4 sm:grid-cols-2">
                <TextField
                  label={t("website.widgets.origins")}
                  hint={t("website.widgets.originsHint")}
                  placeholder="https://www.example.com"
                  value={origins}
                  onChange={(e) => setOrigins(e.target.value)}
                  error={errors.allowed_origins?.[0]}
                />
                <SelectField
                  label={t("website.widgets.corners")}
                  value={radius}
                  onChange={(e) => setRadius(e.target.value)}
                  options={[
                    { value: "", label: t("website.widgets.cornersDefault") },
                    { value: "0px", label: t("website.widgets.cornersSquare") },
                    { value: "16px", label: t("website.widgets.cornersRound") },
                  ]}
                />
              </div>
              {create.isError ? (
                <Alert tone="danger">
                  {errorText(create.error)}
                  {errors.options ? ` ${JSON.stringify(errors.options)}` : ""}
                </Alert>
              ) : null}
            </div>
            <PanelFooter>
              <Button type="submit" size="sm" loading={create.isPending}>
                {t("website.widgets.create")}
              </Button>
            </PanelFooter>
          </form>
        </RuledPanel>
      ) : null}
      <Card title={t("website.widgets.otherBuilders")}>
        <ul className="list-disc space-y-1 pl-5 text-sm">
          <li>{t("website.widgets.wordpress")}</li>
          <li>{t("website.widgets.wix")}</li>
          <li>{t("website.widgets.squarespace")}</li>
        </ul>
      </Card>
    </div>
  );
}

// --- testimonials -------------------------------------------------------------------------------

export function ReviewsTab() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canManage = usePermission("sites.widget.manage");
  const reviews = useQuery({
    queryKey: ["testimonials"],
    queryFn: async () => unwrap(await api.GET("/api/v1/testimonials")),
  });
  const quoteId = useId();
  const [form, setForm] = useState({ quote: "", author: "", role: "", rating: "5" });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["testimonials"] });
  const create = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/testimonials", {
          body: { ...form, rating: form.rating ? Number(form.rating) : null },
        }),
      ),
    onSuccess: () => {
      setForm({ quote: "", author: "", role: "", rating: "5" });
      refresh();
    },
  });
  const toggle = useMutation({
    mutationFn: async ({ id, published }: { id: string; published: boolean }) =>
      unwrap(
        await api.PATCH("/api/v1/testimonials/{id}", {
          params: { path: { id } },
          body: { published },
        }),
      ),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: async (id: string) =>
      unwrap(await api.DELETE("/api/v1/testimonials/{id}", { params: { path: { id } } })),
    onSuccess: refresh,
  });
  if (!reviews.data) return <Spinner label={t("grid.loading")} />;
  const errors = fieldErrors(create.error);
  return (
    <div className="max-w-4xl space-y-6">
      <p className="text-sm text-muted-foreground">{t("website.reviews.intro")}</p>
      <RuledPanel title={t("website.tabs.reviews")} flush>
        {reviews.data.results.length ? (
          <PanelRows>
            {reviews.data.results.map((r) => (
              <PanelRow key={r.id}>
                <NamePlate
                  name={<blockquote className="font-normal">“{r.quote}”</blockquote>}
                  context={[
                    [r.author, r.role].filter(Boolean).join(", "),
                    r.rating ? t("website.reviews.stars", { n: r.rating }) : "",
                    !r.published ? t("website.reviews.hidden") : "",
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                  aside={
                    canManage ? (
                      <>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => toggle.mutate({ id: r.id, published: !r.published })}
                        >
                          {r.published ? t("website.reviews.hide") : t("website.reviews.show")}
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          className="text-muted-foreground"
                          aria-label={t("website.removeNamed", { name: r.author })}
                          onClick={() => remove.mutate(r.id)}
                        >
                          {t("website.remove")}
                        </Button>
                      </>
                    ) : null
                  }
                />
              </PanelRow>
            ))}
          </PanelRows>
        ) : (
          <p className="px-5 py-4 text-sm text-muted-foreground">
            {t("designS8.website.noTestimonials")}
          </p>
        )}
      </RuledPanel>
      {canManage ? (
        <RuledPanel title={t("website.reviews.add")} flush>
          <form
            aria-label={t("website.reviews.add")}
            onSubmit={(e) => {
              e.preventDefault();
              create.mutate();
            }}
          >
            <div className="space-y-4 px-5 py-4">
              <div className="flex flex-col gap-1">
                <label htmlFor={quoteId} className="text-sm font-medium">
                  {t("website.reviews.quote")}
                </label>
                <textarea
                  id={quoteId}
                  required
                  rows={3}
                  className="w-full rounded-md border border-field bg-surface px-3 py-2 text-sm aria-[invalid=true]:border-danger"
                  value={form.quote}
                  aria-invalid={errors.quote ? true : undefined}
                  onChange={(e) => setForm({ ...form, quote: e.target.value })}
                />
                {errors.quote ? (
                  <p className="text-xs text-danger" role="alert">
                    {errors.quote[0]}
                  </p>
                ) : null}
              </div>
              <div className="grid gap-4 sm:grid-cols-3">
                <TextField
                  label={t("website.reviews.author")}
                  required
                  value={form.author}
                  onChange={(e) => setForm({ ...form, author: e.target.value })}
                />
                <TextField
                  label={t("website.reviews.role")}
                  value={form.role}
                  onChange={(e) => setForm({ ...form, role: e.target.value })}
                />
                <SelectField
                  label={t("website.reviews.rating")}
                  value={form.rating}
                  onChange={(e) => setForm({ ...form, rating: e.target.value })}
                  options={[
                    { value: "", label: t("website.reviews.noRating") },
                    ...["5", "4", "3", "2", "1"].map((n) => ({ value: n, label: n })),
                  ]}
                />
              </div>
            </div>
            <PanelFooter>
              <Button type="submit" size="sm" loading={create.isPending}>
                {t("website.reviews.add")}
              </Button>
            </PanelFooter>
          </form>
        </RuledPanel>
      ) : null}
    </div>
  );
}
