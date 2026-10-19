import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, Tabs, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useState } from "react";

import { api, usePermission } from "../api";
import { BlogTab } from "./BlogTab";
import { errorText, fieldErrors, useBrandingOptions } from "./helpers";
import { Card } from "./shared";
import { contrast, isHex, onColour, readableOnWhite, WHITE } from "./contrast";
import { ProfilesTab } from "./ProfilesTab";
import { SiteTab } from "./SiteTab";
import { uploadImage } from "./upload";
import { ReviewsTab, WidgetsTab } from "./WidgetsTab";

type BrandKit = components["schemas"]["BrandKit"];
type Domain = components["schemas"]["Domain"];

type Tab = "branding" | "domains" | "widgets" | "reviews" | "site" | "blog" | "profiles";

/** Website & branding (E24): brand kit with live preview, custom domains, widgets with
 * embed codes, testimonials, the website builder and public profile moderation. */
export function WebsitePage() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<Tab>(() => {
    const wanted = new URLSearchParams(window.location.search).get("tab");
    return (
      ["branding", "domains", "widgets", "reviews", "site", "blog", "profiles"] as const
    ).includes(wanted as Tab)
      ? (wanted as Tab)
      : "branding";
  });
  const canModerate = usePermission("sites.profile.moderate");
  const tabs = [
    { key: "branding" as const, label: t("website.tabs.branding") },
    { key: "domains" as const, label: t("website.tabs.domains") },
    { key: "widgets" as const, label: t("website.tabs.widgets") },
    { key: "reviews" as const, label: t("website.tabs.reviews") },
    { key: "site" as const, label: t("website.tabs.site") },
    { key: "blog" as const, label: t("blogPosts.tab") },
    ...(canModerate ? [{ key: "profiles" as const, label: t("website.tabs.profiles") }] : []),
  ];
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">{t("website.title")}</h1>
      <Tabs label={t("website.title")} tabs={tabs} value={tab} onChange={setTab}>
        {tab === "branding" ? <BrandingTab /> : null}
        {tab === "domains" ? <DomainsTab /> : null}
        {tab === "widgets" ? <WidgetsTab /> : null}
        {tab === "reviews" ? <ReviewsTab /> : null}
        {tab === "site" ? <SiteTab /> : null}
        {tab === "blog" ? <BlogTab /> : null}
        {tab === "profiles" ? <ProfilesTab /> : null}
      </Tabs>
    </div>
  );
}

// --- branding -----------------------------------------------------------------------------------

interface KitForm {
  primary_colour: string;
  secondary_colour: string;
  font: string;
  email_header: string;
  email_footer: string;
  document_footer: string;
  app_name: string;
  social_links: Record<string, string>;
  hide_powered_by: boolean;
}

const EMPTY: KitForm = {
  primary_colour: "#2563eb",
  secondary_colour: "#0f172a",
  font: "",
  email_header: "",
  email_footer: "",
  document_footer: "",
  app_name: "",
  social_links: {},
  hide_powered_by: false,
};

function toForm(kit: BrandKit | undefined): KitForm {
  if (!kit) return EMPTY;
  return {
    primary_colour: kit.primary_colour || EMPTY.primary_colour,
    secondary_colour: kit.secondary_colour || EMPTY.secondary_colour,
    font: kit.font,
    email_header: kit.email_header,
    email_footer: kit.email_footer,
    document_footer: kit.document_footer,
    app_name: kit.app_name,
    social_links: { ...kit.social_links },
    hide_powered_by: kit.hide_powered_by,
  };
}

function ColourField({
  label,
  value,
  onChange,
  error,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  error?: string;
}) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <div className="flex items-center gap-2">
        <input
          type="color"
          aria-hidden="true"
          tabIndex={-1}
          className="h-10 w-12 rounded-md border border-border"
          value={isHex(value) ? value : "#000000"}
          onChange={(e) => onChange(e.target.value)}
        />
        <input
          id={id}
          className="h-10 w-32 rounded-md border border-border bg-background px-3 font-mono text-sm"
          value={value}
          aria-invalid={error || !isHex(value) ? true : undefined}
          onChange={(e) => onChange(e.target.value)}
        />
      </div>
      {error ? (
        <p className="text-xs text-danger" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}

function ImageField({
  label,
  current,
  onUploaded,
}: {
  label: string;
  current: string | null | undefined;
  onUploaded: (id: string | null) => void;
}) {
  const { t } = useTranslation();
  const id = useId();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <div className="flex flex-wrap items-center gap-2">
        {current ? (
          <img
            src={`/api/v1/public/assets/${current}`}
            alt=""
            className="h-10 max-w-32 rounded border border-border object-contain"
          />
        ) : null}
        <input
          id={id}
          type="file"
          accept="image/png,image/jpeg,image/webp,image/svg+xml,image/x-icon"
          className="text-sm"
          disabled={busy}
          onChange={async (e) => {
            const file = e.target.files?.[0];
            if (!file) return;
            setBusy(true);
            setError("");
            try {
              onUploaded(await uploadImage(file));
            } catch {
              setError(t("website.uploadFailed"));
            } finally {
              setBusy(false);
            }
          }}
        />
        {current ? (
          <Button size="sm" variant="ghost" onClick={() => onUploaded(null)}>
            {t("website.remove")}
          </Button>
        ) : null}
      </div>
      {error ? (
        <p className="text-xs text-danger" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}

function BrandingTab() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canEdit = usePermission("sites.branding.manage");
  const options = useBrandingOptions();
  const kits = useQuery({
    queryKey: ["brand-kits"],
    queryFn: async () => unwrap(await api.GET("/api/v1/brand-kits")),
  });
  const branches = useQuery({
    queryKey: ["branches"],
    queryFn: async () => unwrap(await api.GET("/api/v1/branches")),
  });
  const [branch, setBranch] = useState("");
  const kit = kits.data?.find((k) => (k.branch ?? "") === branch);
  const [form, setForm] = useState<KitForm>(EMPTY);
  useEffect(() => setForm(toForm(kit)), [kit]);
  const save = useMutation({
    mutationFn: async (extra: Record<string, string | null>) =>
      unwrap(
        await api.POST("/api/v1/brand-kits", {
          body: { ...form, ...extra, branch: branch || null },
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["brand-kits"] }),
  });
  const remove = useMutation({
    mutationFn: async (id: string) =>
      unwrap(await api.DELETE("/api/v1/brand-kits/{id}", { params: { path: { id } } })),
    onSuccess: () => {
      setBranch("");
      void queryClient.invalidateQueries({ queryKey: ["brand-kits"] });
    },
  });
  if (!kits.data || !options.data) return <Spinner label={t("grid.loading")} />;
  const errors = fieldErrors(save.error);
  const set = <K extends keyof KitForm>(key: K, value: KitForm[K]) =>
    setForm({ ...form, [key]: value });
  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,420px)]">
      <form
        aria-label={t("website.branding.form")}
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate({});
        }}
      >
        <SelectField
          label={t("website.branding.applyTo")}
          value={branch}
          onChange={(e) => setBranch(e.target.value)}
          options={[
            { value: "", label: t("website.branding.organisation") },
            ...(branches.data?.results ?? []).map((b) => ({ value: b.id, label: b.name })),
          ]}
          hint={branch ? t("website.branding.branchHint") : undefined}
        />
        <Card title={t("website.branding.logos")}>
          <div className="grid gap-4 sm:grid-cols-2">
            {(
              [
                ["logo", t("website.branding.logo")],
                ["logo_dark", t("website.branding.logoDark")],
                ["favicon", t("website.branding.favicon")],
                ["app_icon", t("website.branding.appIcon")],
              ] as const
            ).map(([key, label]) => (
              <ImageField
                key={key}
                label={label}
                current={kit?.[key]}
                onUploaded={(id) => save.mutate({ [key]: id })}
              />
            ))}
          </div>
        </Card>
        <Card title={t("website.branding.colours")}>
          <div className="flex flex-wrap gap-4">
            <ColourField
              label={t("website.branding.primary")}
              value={form.primary_colour}
              onChange={(v) => set("primary_colour", v)}
              error={errors.primary_colour?.[0]}
            />
            <ColourField
              label={t("website.branding.secondary")}
              value={form.secondary_colour}
              onChange={(v) => set("secondary_colour", v)}
              error={errors.secondary_colour?.[0]}
            />
          </div>
          <ContrastReport primary={form.primary_colour} />
          <SelectField
            label={t("website.branding.font")}
            value={form.font}
            onChange={(e) => set("font", e.target.value)}
            options={[
              { value: "", label: t("website.branding.systemFont") },
              ...options.data.fonts.map((f) => ({ value: f, label: f })),
            ]}
          />
        </Card>
        <Card title={t("website.branding.emailsDocuments")}>
          <TextField
            label={t("website.branding.emailHeader")}
            value={form.email_header}
            onChange={(e) => set("email_header", e.target.value)}
          />
          <Textarea
            label={t("website.branding.emailFooter")}
            value={form.email_footer}
            onChange={(v) => set("email_footer", v)}
          />
          <Textarea
            label={t("website.branding.documentFooter")}
            value={form.document_footer}
            onChange={(v) => set("document_footer", v)}
          />
          <TextField
            label={t("website.branding.appName")}
            hint={t("website.branding.appNameHint")}
            value={form.app_name}
            onChange={(e) => set("app_name", e.target.value)}
          />
        </Card>
        <Card title={t("website.branding.social")}>
          <div className="grid gap-3 sm:grid-cols-2">
            {options.data.social_networks.map((network) => (
              <TextField
                key={network}
                type="url"
                label={t(`website.social.${network}`)}
                placeholder="https://"
                value={form.social_links[network] ?? ""}
                onChange={(e) =>
                  set("social_links", { ...form.social_links, [network]: e.target.value })
                }
              />
            ))}
          </div>
          {errors.social_links ? <Alert tone="danger">{errors.social_links[0]}</Alert> : null}
        </Card>
        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            className="mt-1"
            checked={form.hide_powered_by}
            disabled={!options.data.white_label}
            onChange={(e) => set("hide_powered_by", e.target.checked)}
          />
          <span>
            {t("website.branding.hidePoweredBy")}
            {!options.data.white_label ? (
              <span className="block text-muted-foreground">
                {t("website.branding.whiteLabelPlan")}
              </span>
            ) : null}
          </span>
        </label>
        {save.isError && !Object.keys(errors).length ? (
          <Alert tone="danger">{errorText(save.error)}</Alert>
        ) : null}
        {save.isSuccess ? <Alert tone="success">{t("website.saved")}</Alert> : null}
        {canEdit ? (
          <div className="flex flex-wrap gap-2">
            <Button type="submit" loading={save.isPending} disabled={!isHex(form.primary_colour)}>
              {t("website.save")}
            </Button>
            {branch && kit ? (
              <Button variant="ghost" onClick={() => remove.mutate(kit.id)}>
                {t("website.branding.removeOverride")}
              </Button>
            ) : null}
          </div>
        ) : null}
      </form>
      <ThemePreview form={form} logo={kit?.logo ?? kits.data.find((k) => !k.branch)?.logo} />
    </div>
  );
}

function Textarea({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <textarea
        id={id}
        rows={3}
        className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

/** Live AA check of the chosen colour, with the shades we'll use automatically. */
export function ContrastReport({ primary }: { primary: string }) {
  const { t } = useTranslation();
  if (!isHex(primary)) return null;
  const onWhite = contrast(primary, WHITE);
  const text = onColour(primary);
  const onPrimary = contrast(primary, text);
  const warnings = [
    onWhite < 4.5 ? t("website.contrast.tooLight", { ratio: onWhite }) : "",
    onPrimary < 4.5 ? t("website.contrast.noText", { ratio: onPrimary }) : "",
  ].filter(Boolean);
  return (
    <div aria-live="polite" className="space-y-1 text-sm">
      <p>
        {t("website.contrast.onWhite", { ratio: onWhite })} ·{" "}
        {t("website.contrast.textOnColour", { ratio: onPrimary })}
      </p>
      {warnings.length ? (
        <Alert tone="warning" title={t("website.contrast.title")}>
          <ul className="list-disc pl-5">
            {warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </Alert>
      ) : (
        <p className="text-success">{t("website.contrast.passes")}</p>
      )}
    </div>
  );
}

/** Portal, email and widget preview with the unsaved colours and font. */
function ThemePreview({ form, logo }: { form: KitForm; logo: string | null | undefined }) {
  const { t } = useTranslation();
  const brand = isHex(form.primary_colour) ? form.primary_colour : "#2563eb";
  const link = readableOnWhite(brand);
  const fontFamily = form.font ? `'${form.font}', system-ui, sans-serif` : undefined;
  return (
    <aside aria-label={t("website.preview.title")} className="space-y-4 lg:sticky lg:top-4">
      <h2 className="font-semibold">{t("website.preview.title")}</h2>
      <div
        data-testid="theme-preview"
        className="overflow-hidden rounded-lg border border-border bg-white text-[#111827]"
        style={{ fontFamily }}
      >
        <div className="flex items-center justify-between border-b border-[#e5e7eb] p-3">
          {logo ? (
            <img src={`/api/v1/public/assets/${logo}`} alt="" className="h-8" />
          ) : (
            <span className="font-semibold" style={{ color: link }}>
              {form.app_name || t("website.preview.portal")}
            </span>
          )}
          <span className="text-sm" style={{ color: link }}>
            {t("website.preview.link")}
          </span>
        </div>
        <div className="space-y-3 p-4">
          <p className="text-lg font-semibold" style={{ color: link }}>
            {t("website.preview.heading")}
          </p>
          <p className="text-sm">{t("website.preview.body")}</p>
          <span
            className="inline-block rounded-md px-4 py-2 text-sm font-semibold"
            style={{ background: brand, color: onColour(brand) }}
          >
            {t("website.preview.button")}
          </span>
        </div>
        <div className="border-t border-[#e5e7eb] p-3 text-xs text-[#4b5563]">
          {form.email_footer || t("website.preview.footer")}
          {!form.hide_powered_by ? ` · ${t("website.poweredBy")}` : ""}
        </div>
      </div>
    </aside>
  );
}

// --- domains ------------------------------------------------------------------------------------

function statusTone(domain: Domain): "success" | "warning" | "danger" | "info" {
  if (domain.verification_status === "failed" || domain.ssl_status === "failed") return "danger";
  if (domain.ssl_status === "active") return "success";
  return "warning";
}

function DomainsTab() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const canManage = usePermission("sites.domain.manage");
  const options = useBrandingOptions();
  const domains = useQuery({
    queryKey: ["domains"],
    queryFn: async () => unwrap(await api.GET("/api/v1/domains")),
    refetchInterval: (query) =>
      query.state.data?.some((d) => d.ssl_status !== "active" && d.verification_status !== "failed")
        ? 15_000
        : false,
  });
  const [hostname, setHostname] = useState("");
  const [purpose, setPurpose] = useState<"app" | "site">("app");
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["domains"] });
  const add = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/v1/domains", { body: { hostname, purpose } })),
    onSuccess: () => {
      setHostname("");
      refresh();
    },
  });
  const verify = useMutation({
    mutationFn: async (id: string) =>
      unwrap(await api.POST("/api/v1/domains/{id}/verify", { params: { path: { id } } })),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: async (id: string) =>
      unwrap(await api.DELETE("/api/v1/domains/{id}", { params: { path: { id } } })),
    onSuccess: refresh,
  });
  if (!domains.data || !options.data) return <Spinner label={t("grid.loading")} />;
  const addErrors = fieldErrors(add.error);
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">{t("website.domains.intro")}</p>
      {!options.data.custom_domain ? (
        <Alert tone="info">{t("website.domains.needsPlan")}</Alert>
      ) : null}
      {canManage && options.data.custom_domain ? (
        <form
          aria-label={t("website.domains.add")}
          className="flex flex-wrap items-end gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            add.mutate();
          }}
        >
          <TextField
            label={t("website.domains.hostname")}
            placeholder="portal.example.com"
            value={hostname}
            required
            onChange={(e) => setHostname(e.target.value)}
            error={addErrors.hostname?.[0]}
          />
          <SelectField
            label={t("website.domains.purpose")}
            value={purpose}
            onChange={(e) => setPurpose(e.target.value as "app" | "site")}
            options={[
              { value: "app", label: t("website.domains.purposeApp") },
              { value: "site", label: t("website.domains.purposeSite") },
            ]}
          />
          <Button type="submit" loading={add.isPending}>
            {t("website.domains.add")}
          </Button>
        </form>
      ) : null}
      {add.isError && !addErrors.hostname ? (
        <Alert tone="danger">{errorText(add.error)}</Alert>
      ) : null}
      {domains.data.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("website.domains.none")}</p>
      ) : null}
      {domains.data.map((domain) => (
        <Card key={domain.id} title={domain.hostname}>
          <Alert tone={statusTone(domain)}>
            <p>
              {t("website.domains.verification")}:{" "}
              <strong>{t(`website.domains.verification_${domain.verification_status}`)}</strong> ·{" "}
              {t("website.domains.certificate")}:{" "}
              <strong>{t(`website.domains.ssl_${domain.ssl_status}`)}</strong>
            </p>
            {domain.status_detail ? <p>{domain.status_detail}</p> : null}
            {domain.last_checked_at ? (
              <p className="text-xs text-muted-foreground">
                {t("website.domains.lastChecked", {
                  when: formatDateTime(domain.last_checked_at, i18n.language),
                })}
              </p>
            ) : null}
          </Alert>
          {domain.ssl_status === "active" ? (
            <p className="text-sm">
              {t("website.domains.live")}{" "}
              <a className="underline" href={domain.url}>
                {domain.url}
              </a>
            </p>
          ) : (
            <>
              <p className="text-sm">{t("website.domains.instructions")}</p>
              <table className="w-full text-left text-sm">
                <caption className="sr-only">{t("website.domains.records")}</caption>
                <thead>
                  <tr>
                    <th scope="col">{t("website.domains.type")}</th>
                    <th scope="col">{t("website.domains.name")}</th>
                    <th scope="col">{t("website.domains.value")}</th>
                  </tr>
                </thead>
                <tbody>
                  {domain.dns_records.map((r) => (
                    <tr key={r.record_type} className="border-t border-border">
                      <td className="py-1 pr-2">{r.record_type}</td>
                      <td className="break-all py-1 pr-2 font-mono text-xs">{r.name}</td>
                      <td className="break-all py-1 font-mono text-xs">{r.value}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
          {canManage ? (
            <div className="flex flex-wrap gap-2">
              {domain.ssl_status !== "active" ? (
                <Button size="sm" variant="secondary" onClick={() => verify.mutate(domain.id)}>
                  {t("website.domains.checkNow")}
                </Button>
              ) : null}
              <Button
                size="sm"
                variant="ghost"
                aria-label={t("website.domains.removeNamed", { host: domain.hostname })}
                onClick={() => {
                  if (window.confirm(t("website.domains.confirmRemove", { host: domain.hostname })))
                    remove.mutate(domain.id);
                }}
              >
                {t("website.remove")}
              </Button>
            </div>
          ) : null}
        </Card>
      ))}
    </div>
  );
}
