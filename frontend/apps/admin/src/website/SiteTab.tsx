import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useState } from "react";

import { api, usePermission } from "../api";
import { AiContentHelper } from "../ai/AiParts";
import { errorText, fieldErrors } from "./helpers";
import { Card } from "./shared";
import { uploadImage } from "./upload";

type Site = components["schemas"]["Site"];
type SitePage = components["schemas"]["SitePage"];
type BlockType = components["schemas"]["BlockType"];
type Block = { id: string; type: string; props: Record<string, unknown> };

/** The website builder (FR-24-4): site settings and SEO, pages, blocks, preview, publish. */
export function SiteTab() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canManage = usePermission("sites.site.manage");
  const sites = useQuery({
    queryKey: ["sites"],
    queryFn: async () => unwrap(await api.GET("/api/v1/sites")),
  });
  const create = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/sites", { body: {} })),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["sites"] });
      void queryClient.invalidateQueries({ queryKey: ["site-pages"] });
    },
  });
  if (!sites.data) return <Spinner label={t("grid.loading")} />;
  const site = sites.data[0];
  if (!site) {
    return (
      <div className="space-y-3">
        <p className="text-sm text-muted-foreground">{t("website.site.intro")}</p>
        {canManage ? (
          <Button loading={create.isPending} onClick={() => create.mutate()}>
            {t("website.site.create")}
          </Button>
        ) : null}
        {create.isError ? <Alert tone="danger">{errorText(create.error)}</Alert> : null}
      </div>
    );
  }
  return (
    <div className="space-y-6">
      <SiteSettings site={site} />
      <Pages />
    </div>
  );
}

function SiteSettings({ site }: { site: Site }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canManage = usePermission("sites.site.manage");
  const canPublish = usePermission("sites.site.publish");
  const themes = useQuery({
    queryKey: ["site-themes"],
    queryFn: async () => unwrap(await api.GET("/api/v1/sites/themes")),
    staleTime: 10 * 60_000,
  });
  const [form, setForm] = useState(site);
  useEffect(() => setForm(site), [site]);
  const save = useMutation({
    mutationFn: async (body: Partial<Site>) =>
      unwrap(
        await api.PATCH("/api/v1/sites/{id}", {
          params: { path: { id: site.id } },
          body: body as never,
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["sites"] }),
  });
  const errors = fieldErrors(save.error);
  const descriptionId = useId();
  return (
    <Card title={t("website.site.settings")}>
      <p className="text-sm">
        {site.published ? t("website.site.liveAt") : t("website.site.notLive")}{" "}
        {site.url ? (
          <a className="underline" href={site.url} target="_blank" rel="noreferrer">
            {site.url}
          </a>
        ) : null}
      </p>
      <form
        aria-label={t("website.site.settings")}
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          // Editable settings only ("published" has its own button).
          const keys = [
            "name",
            "theme",
            "seo_title",
            "meta_description",
            "business_type",
            "analytics_id",
            "tag_manager_id",
            "cookie_banner",
          ] as const;
          save.mutate(Object.fromEntries(keys.map((k) => [k, form[k]])) as Partial<Site>);
        }}
      >
        <div className="grid gap-3 sm:grid-cols-2">
          <TextField
            label={t("website.site.name")}
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
          <SelectField
            label={t("website.site.theme")}
            value={form.theme}
            hint={themes.data?.find((th) => th.key === form.theme)?.description}
            onChange={(e) => setForm({ ...form, theme: e.target.value })}
            options={(themes.data ?? []).map((th) => ({ value: th.key, label: th.title }))}
            error={errors.theme?.[0]}
          />
          <TextField
            label={t("website.site.seoTitle")}
            value={form.seo_title ?? ""}
            onChange={(e) => setForm({ ...form, seo_title: e.target.value })}
          />
          <SelectField
            label={t("website.site.businessType")}
            value={form.business_type ?? "EducationalOrganization"}
            onChange={(e) => setForm({ ...form, business_type: e.target.value })}
            options={[
              { value: "EducationalOrganization", label: t("website.site.educational") },
              { value: "LocalBusiness", label: t("website.site.localBusiness") },
            ]}
          />
          <TextField
            label={t("website.site.analytics")}
            placeholder="G-XXXXXXXXXX"
            value={form.analytics_id ?? ""}
            onChange={(e) => setForm({ ...form, analytics_id: e.target.value.trim() })}
            error={errors.analytics_id?.[0]}
          />
          <TextField
            label={t("website.site.tagManager")}
            placeholder="GTM-XXXXXXX"
            value={form.tag_manager_id ?? ""}
            onChange={(e) => setForm({ ...form, tag_manager_id: e.target.value.trim() })}
            error={errors.tag_manager_id?.[0]}
          />
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor={descriptionId} className="text-sm font-medium">
            {t("website.site.metaDescription")}
          </label>
          <textarea
            id={descriptionId}
            rows={2}
            maxLength={300}
            className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
            value={form.meta_description ?? ""}
            onChange={(e) => setForm({ ...form, meta_description: e.target.value })}
          />
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={form.cookie_banner ?? true}
            onChange={(e) => setForm({ ...form, cookie_banner: e.target.checked })}
          />
          {t("website.site.cookieBanner")}
        </label>
        {save.isError && !Object.keys(errors).length ? (
          <Alert tone="danger">{errorText(save.error)}</Alert>
        ) : null}
        <div className="flex flex-wrap gap-2">
          {canManage ? (
            <Button type="submit" loading={save.isPending}>
              {t("website.save")}
            </Button>
          ) : null}
          {canPublish ? (
            <Button variant="secondary" onClick={() => save.mutate({ published: !site.published })}>
              {site.published ? t("website.site.takeOffline") : t("website.site.goLive")}
            </Button>
          ) : null}
        </div>
      </form>
    </Card>
  );
}

function Pages() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canManage = usePermission("sites.site.manage");
  const pages = useQuery({
    queryKey: ["site-pages"],
    queryFn: async () => unwrap(await api.GET("/api/v1/sites/pages")),
  });
  const [editing, setEditing] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const create = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/sites/pages", { body: { title } })),
    onSuccess: (page) => {
      setTitle("");
      setEditing(page.id);
      void queryClient.invalidateQueries({ queryKey: ["site-pages"] });
    },
  });
  if (!pages.data) return <Spinner label={t("grid.loading")} />;
  const page = pages.data.results.find((p) => p.id === editing);
  if (page) return <PageEditor page={page} onClose={() => setEditing(null)} />;
  return (
    <Card title={t("website.pages.title")}>
      <table className="w-full text-left text-sm">
        <thead>
          <tr>
            <th scope="col">{t("website.pages.page")}</th>
            <th scope="col">{t("website.pages.address")}</th>
            <th scope="col">{t("website.pages.status")}</th>
            <th scope="col">
              <span className="sr-only">{t("website.pages.actions")}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {pages.data.results.map((p) => (
            <tr key={p.id} className="border-t border-border">
              <td className="py-2">{p.title}</td>
              <td className="py-2 font-mono text-xs">/{p.path}</td>
              <td className="py-2">{t(`website.pages.status_${p.status}`)}</td>
              <td className="py-2 text-right">
                <Button
                  size="sm"
                  variant="secondary"
                  aria-label={t("website.pages.editNamed", { title: p.title })}
                  onClick={() => setEditing(p.id)}
                >
                  {t("website.pages.edit")}
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {canManage ? (
        <form
          aria-label={t("website.pages.new")}
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <TextField
            label={t("website.pages.newTitle")}
            value={title}
            required
            onChange={(e) => setTitle(e.target.value)}
            error={fieldErrors(create.error).path?.[0]}
          />
          <Button type="submit" loading={create.isPending}>
            {t("website.pages.add")}
          </Button>
        </form>
      ) : null}
    </Card>
  );
}

function newId(): string {
  return `b${Math.random().toString(36).slice(2, 9)}`;
}

function toBlocks(page: SitePage): Block[] {
  return (page.blocks ?? []).map((b) => ({
    id: String(b.id ?? newId()),
    type: String(b.type),
    props: (b.props as Record<string, unknown>) ?? {},
  }));
}

function PageEditor({ page, onClose }: { page: SitePage; onClose: () => void }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const canManage = usePermission("sites.site.manage");
  const canPublish = usePermission("sites.site.publish");
  const types = useQuery({
    queryKey: ["site-blocks"],
    queryFn: async () => unwrap(await api.GET("/api/v1/sites/blocks")),
    staleTime: 10 * 60_000,
  });
  const versions = useQuery({
    queryKey: ["site-page-versions", page.id],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/sites/pages/{id}/versions", { params: { path: { id: page.id } } }),
      ),
  });
  const [meta, setMeta] = useState({
    title: page.title,
    nav_label: page.nav_label ?? "",
    show_in_nav: page.show_in_nav ?? true,
    seo_title: page.seo_title ?? "",
    meta_description: page.meta_description ?? "",
  });
  const [blocks, setBlocks] = useState<Block[]>(() => toBlocks(page));
  const [adding, setAdding] = useState("text");
  const [preview, setPreview] = useState<string | null>(null);
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["site-pages"] });
    void queryClient.invalidateQueries({ queryKey: ["site-page-versions", page.id] });
  };
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.PATCH("/api/v1/sites/pages/{id}", {
          params: { path: { id: page.id } },
          body: { ...meta, blocks: blocks as never },
        }),
      ),
    onSuccess: refresh,
  });
  const act = useMutation({
    mutationFn: async (action: "publish" | "unpublish") => {
      if (action === "publish") await save.mutateAsync();
      const path =
        action === "publish"
          ? ("/api/v1/sites/pages/{id}/publish" as const)
          : ("/api/v1/sites/pages/{id}/unpublish" as const);
      return unwrap(await api.POST(path, { params: { path: { id: page.id } } }));
    },
    onSuccess: refresh,
  });
  const showPreview = useMutation({
    mutationFn: async () => {
      await save.mutateAsync();
      return unwrap(
        await api.GET("/api/v1/sites/pages/{id}/preview", { params: { path: { id: page.id } } }),
      );
    },
    onSuccess: (result) => setPreview(result.html),
  });
  const restore = useMutation({
    mutationFn: async (version: number) =>
      unwrap(
        await api.POST("/api/v1/sites/pages/{id}/restore", {
          params: { path: { id: page.id } },
          body: { version },
        }),
      ),
    onSuccess: (restored) => {
      setBlocks(toBlocks(restored));
      refresh();
    },
  });
  const remove = useMutation({
    mutationFn: async () =>
      unwrap(await api.DELETE("/api/v1/sites/pages/{id}", { params: { path: { id: page.id } } })),
    onSuccess: () => {
      refresh();
      onClose();
    },
  });
  if (!types.data) return <Spinner label={t("grid.loading")} />;
  const blockErrors = (fieldErrors(save.error).blocks ?? {}) as unknown as Record<string, unknown>;
  const move = (i: number, step: number) => {
    const next = [...blocks];
    const [item] = next.splice(i, 1);
    next.splice(i + step, 0, item!);
    setBlocks(next);
  };
  return (
    <section aria-label={t("website.pages.editing", { title: page.title })} className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-xl font-semibold">
          {t("website.pages.editing", { title: page.title })}
        </h2>
        <Button variant="ghost" onClick={onClose}>
          {t("website.pages.back")}
        </Button>
      </div>
      <p className="text-sm text-muted-foreground">
        {t(`website.pages.status_${page.status}`)}
        {page.live_version_number
          ? ` · ${t("website.pages.liveVersion", { n: page.live_version_number })}`
          : ""}
      </p>
      <Card title={t("website.pages.details")}>
        <div className="grid gap-3 sm:grid-cols-2">
          <TextField
            label={t("website.pages.pageTitle")}
            value={meta.title}
            onChange={(e) => setMeta({ ...meta, title: e.target.value })}
          />
          <TextField
            label={t("website.pages.navLabel")}
            value={meta.nav_label}
            onChange={(e) => setMeta({ ...meta, nav_label: e.target.value })}
          />
          <TextField
            label={t("website.pages.seoTitle")}
            value={meta.seo_title}
            onChange={(e) => setMeta({ ...meta, seo_title: e.target.value })}
          />
          <TextField
            label={t("website.pages.metaDescription")}
            value={meta.meta_description}
            maxLength={300}
            onChange={(e) => setMeta({ ...meta, meta_description: e.target.value })}
          />
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={meta.show_in_nav}
            onChange={(e) => setMeta({ ...meta, show_in_nav: e.target.checked })}
          />
          {t("website.pages.showInNav")}
        </label>
      </Card>
      {canManage ? (
        <AiContentHelper
          kind="page"
          title={meta.title}
          onUse={(draft) => {
            setMeta((m) => ({
              ...m,
              meta_description: draft.meta_description || m.meta_description,
            }));
            setBlocks((all) => [
              ...all,
              { id: newId(), type: "text", props: { heading: draft.title, body: draft.body } },
            ]);
          }}
        />
      ) : null}
      <ol className="space-y-3" aria-label={t("website.pages.blocks")}>
        {blocks.map((block, i) => {
          const type = types.data.find((b) => b.key === block.type);
          const error = blockErrors[String(i)];
          return (
            <li key={block.id} className="space-y-3 rounded-lg border border-border p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h3 className="font-medium">
                  {i + 1}. {type?.title ?? block.type}
                </h3>
                <div className="flex gap-1">
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={i === 0}
                    aria-label={t("website.pages.moveUp", { n: i + 1 })}
                    onClick={() => move(i, -1)}
                  >
                    ↑
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={i === blocks.length - 1}
                    aria-label={t("website.pages.moveDown", { n: i + 1 })}
                    onClick={() => move(i, 1)}
                  >
                    ↓
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={t("website.pages.removeBlock", { n: i + 1 })}
                    onClick={() => setBlocks(blocks.filter((_, j) => j !== i))}
                  >
                    {t("website.remove")}
                  </Button>
                </div>
              </div>
              {type ? (
                <BlockFields
                  type={type}
                  props={block.props}
                  onChange={(props) =>
                    setBlocks(blocks.map((b, j) => (j === i ? { ...b, props } : b)))
                  }
                />
              ) : null}
              {error ? (
                <Alert tone="danger">
                  {t("website.pages.blockError")}: {JSON.stringify(error)}
                </Alert>
              ) : null}
            </li>
          );
        })}
      </ol>
      {canManage ? (
        <div className="flex flex-wrap items-end gap-2">
          <SelectField
            label={t("website.pages.blockType")}
            value={adding}
            onChange={(e) => setAdding(e.target.value)}
            options={types.data.map((b) => ({ value: b.key, label: b.title }))}
          />
          <Button
            variant="secondary"
            onClick={() => setBlocks([...blocks, { id: newId(), type: adding, props: {} }])}
          >
            {t("website.pages.addBlock")}
          </Button>
        </div>
      ) : null}
      {save.isError && !Object.keys(blockErrors).length ? (
        <Alert tone="danger">{errorText(save.error)}</Alert>
      ) : null}
      {act.isError ? <Alert tone="danger">{errorText(act.error)}</Alert> : null}
      {act.isSuccess ? <Alert tone="success">{t("website.pages.published")}</Alert> : null}
      <div className="flex flex-wrap gap-2">
        {canManage ? (
          <Button loading={save.isPending} onClick={() => save.mutate()}>
            {t("website.pages.saveDraft")}
          </Button>
        ) : null}
        <Button
          variant="secondary"
          loading={showPreview.isPending}
          onClick={() => showPreview.mutate()}
        >
          {t("website.pages.preview")}
        </Button>
        {canPublish ? (
          <Button variant="secondary" loading={act.isPending} onClick={() => act.mutate("publish")}>
            {t("website.pages.publish")}
          </Button>
        ) : null}
        {canPublish && page.live_version_number && page.path ? (
          <Button variant="ghost" onClick={() => act.mutate("unpublish")}>
            {t("website.pages.unpublish")}
          </Button>
        ) : null}
        {canManage && page.path ? (
          <Button
            variant="danger"
            onClick={() => {
              if (window.confirm(t("website.pages.confirmDelete", { title: page.title })))
                remove.mutate();
            }}
          >
            {t("website.pages.delete")}
          </Button>
        ) : null}
      </div>
      {preview !== null ? (
        <iframe
          title={t("website.pages.previewOf", { title: page.title })}
          sandbox=""
          srcDoc={preview}
          className="h-[600px] w-full rounded-md border border-border"
        />
      ) : null}
      {versions.data?.length ? (
        <Card title={t("website.pages.versions")}>
          <ul className="space-y-1 text-sm">
            {versions.data.map((v) => (
              <li key={v.id} className="flex flex-wrap items-center gap-2">
                <span>
                  {t("website.pages.version", { n: v.number })} ·{" "}
                  {formatDateTime(v.created_at, i18n.language)}
                  {v.published_by_name ? ` · ${v.published_by_name}` : ""}
                </span>
                {canManage ? (
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={t("website.pages.restoreVersion", { n: v.number })}
                    onClick={() => restore.mutate(v.number)}
                  >
                    {t("website.pages.restore")}
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
        </Card>
      ) : null}
    </section>
  );
}

/** Form controls generated from the block type's field list. */
function BlockFields({
  type,
  props,
  onChange,
}: {
  type: BlockType;
  props: Record<string, unknown>;
  onChange: (props: Record<string, unknown>) => void;
}) {
  const { t } = useTranslation();
  const set = (name: string, value: unknown) => onChange({ ...props, [name]: value });
  const label = (name: string) => t(`website.blockFields.${name}`, { defaultValue: name });
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {type.fields.map((field) => {
        const value = props[field.name];
        if (field.kind === "textarea")
          return (
            <BlockTextarea
              key={field.name}
              label={label(field.name)}
              required={field.is_required}
              value={String(value ?? "")}
              onChange={(v) => set(field.name, v)}
            />
          );
        if (field.kind === "image")
          return (
            <BlockImage
              key={field.name}
              label={label(field.name)}
              value={value ? String(value) : ""}
              onChange={(v) => set(field.name, v)}
            />
          );
        if (field.kind === "items")
          return (
            <FaqItems
              key={field.name}
              value={(value as { question: string; answer: string }[] | undefined) ?? []}
              onChange={(v) => set(field.name, v)}
            />
          );
        if (field.kind === "services")
          return (
            <TextField
              key={field.name}
              label={label(field.name)}
              hint={t("website.pages.servicesHint")}
              value={((value as string[] | undefined) ?? []).join(", ")}
              onChange={(e) =>
                set(
                  field.name,
                  e.target.value
                    .split(",")
                    .map((s) => s.trim())
                    .filter(Boolean),
                )
              }
            />
          );
        return (
          <TextField
            key={field.name}
            label={label(field.name)}
            required={field.is_required}
            type={field.kind === "number" ? "number" : "text"}
            step={field.kind === "number" ? "any" : undefined}
            hint={field.kind === "href" ? t("website.pages.hrefHint") : undefined}
            maxLength={field.max_length ?? undefined}
            value={String(value ?? "")}
            onChange={(e) => set(field.name, e.target.value)}
          />
        );
      })}
    </div>
  );
}

function BlockTextarea({
  label,
  value,
  required,
  onChange,
}: {
  label: string;
  value: string;
  required: boolean;
  onChange: (value: string) => void;
}) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1 sm:col-span-2">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <textarea
        id={id}
        rows={5}
        required={required}
        className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

function BlockImage({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const { t } = useTranslation();
  const id = useId();
  const [error, setError] = useState("");
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      {value ? (
        <p className="text-xs text-muted-foreground">{t("website.pages.imageSet")}</p>
      ) : null}
      <input
        id={id}
        type="file"
        accept="image/png,image/jpeg,image/webp,image/svg+xml"
        className="text-sm"
        onChange={async (e) => {
          const file = e.target.files?.[0];
          if (!file) return;
          try {
            onChange(await uploadImage(file));
          } catch {
            setError(t("website.uploadFailed"));
          }
        }}
      />
      {error ? (
        <p role="alert" className="text-xs text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}

function FaqItems({
  value,
  onChange,
}: {
  value: { question: string; answer: string }[];
  onChange: (value: { question: string; answer: string }[]) => void;
}) {
  const { t } = useTranslation();
  const change = (i: number, patch: Partial<{ question: string; answer: string }>) =>
    onChange(value.map((item, j) => (j === i ? { ...item, ...patch } : item)));
  return (
    <fieldset className="space-y-2 sm:col-span-2">
      <legend className="text-sm font-medium">{t("website.pages.faqItems")}</legend>
      {value.map((item, i) => (
        <div key={i} className="grid gap-2 sm:grid-cols-2">
          <TextField
            label={t("website.pages.question", { n: i + 1 })}
            value={item.question}
            onChange={(e) => change(i, { question: e.target.value })}
          />
          <TextField
            label={t("website.pages.answer", { n: i + 1 })}
            value={item.answer}
            onChange={(e) => change(i, { answer: e.target.value })}
          />
        </div>
      ))}
      <Button
        size="sm"
        variant="secondary"
        onClick={() => onChange([...value, { question: "", answer: "" }])}
      >
        {t("website.pages.addQuestion")}
      </Button>
    </fieldset>
  );
}
