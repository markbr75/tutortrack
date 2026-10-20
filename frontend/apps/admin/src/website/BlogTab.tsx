import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { api, usePermission } from "../api";
import { Card } from "./shared";

type Post = components["schemas"]["BlogPost"];

const EMPTY = {
  title: "",
  slug: "",
  excerpt: "",
  body: "",
  author_name: "",
  seo_title: "",
  meta_description: "",
};

/** G6 (FR-24-4): blog and news posts on the hosted website (``/blog``, RSS). */
export function BlogTab() {
  const { t } = useTranslation();
  const [editing, setEditing] = useState<Post | "new" | null>(null);
  const posts = useQuery({
    queryKey: ["site-posts"],
    queryFn: async () => unwrap(await api.GET("/api/v1/sites/posts")),
  });
  const canManage = usePermission("sites.site.manage");
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">{t("blogPosts.intro")}</p>
      {canManage && !editing ? (
        <Button onClick={() => setEditing("new")}>{t("blogPosts.new")}</Button>
      ) : null}
      {editing ? (
        <PostEditor post={editing === "new" ? null : editing} onClose={() => setEditing(null)} />
      ) : null}
      {posts.isPending ? <Spinner label={t("grid.loading")} /> : null}
      {posts.data?.results.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("blogPosts.none")}</p>
      ) : null}
      <ul className="divide-y divide-border">
        {posts.data?.results.map((post) => (
          <PostRow key={post.id} post={post} onEdit={() => setEditing(post)} />
        ))}
      </ul>
    </div>
  );
}

function PostRow({ post, onEdit }: { post: Post; onEdit: () => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canPublish = usePermission("sites.site.publish");
  const toggle = useMutation({
    mutationFn: async () =>
      post.status === "published"
        ? unwrap(
            await api.POST("/api/v1/sites/posts/{id}/unpublish", {
              params: { path: { id: post.id } },
            }),
          )
        : unwrap(
            await api.POST("/api/v1/sites/posts/{id}/publish", {
              params: { path: { id: post.id } },
              body: {},
            }),
          ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["site-posts"] }),
  });
  return (
    <li className="flex flex-wrap items-center justify-between gap-2 py-3 text-sm">
      <div>
        <p className="font-medium">{post.title}</p>
        <p className="text-muted-foreground">
          {t(`blogPosts.status.${post.status}`)}
          {post.published_at ? ` · ${formatDateTime(post.published_at)}` : ""} · {post.url}
        </p>
      </div>
      <div className="flex gap-2">
        <Button size="sm" variant="secondary" onClick={onEdit}>
          {t("blogPosts.edit")}
        </Button>
        {canPublish ? (
          <Button size="sm" loading={toggle.isPending} onClick={() => toggle.mutate()}>
            {post.status === "published" ? t("blogPosts.unpublish") : t("blogPosts.publish")}
          </Button>
        ) : null}
      </div>
      {toggle.error ? <Alert tone="danger">{toggle.error.message}</Alert> : null}
    </li>
  );
}

function PostEditor({ post, onClose }: { post: Post | null; onClose: () => void }) {
  const { t } = useTranslation();
  const bodyId = useId();
  const queryClient = useQueryClient();
  const [form, setForm] = useState(() =>
    post
      ? {
          title: post.title,
          slug: post.slug ?? "",
          excerpt: post.excerpt ?? "",
          body: post.body ?? "",
          author_name: post.author_name ?? "",
          seo_title: post.seo_title ?? "",
          meta_description: post.meta_description ?? "",
        }
      : EMPTY,
  );
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) =>
    setForm((f) => ({ ...f, [key]: e.target.value }));
  const save = useMutation({
    mutationFn: async () =>
      post
        ? unwrap(
            await api.PATCH("/api/v1/sites/posts/{id}", {
              params: { path: { id: post.id } },
              body: form,
            }),
          )
        : unwrap(await api.POST("/api/v1/sites/posts", { body: form })),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["site-posts"] });
      onClose();
    },
  });
  return (
    <Card title={post ? t("blogPosts.editTitle") : t("blogPosts.new")}>
      <form
        className="space-y-3"
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <TextField
          label={t("blogPosts.title")}
          value={form.title}
          onChange={set("title")}
          required
        />
        <TextField
          label={t("blogPosts.slug")}
          hint={t("blogPosts.slugHint")}
          value={form.slug}
          onChange={set("slug")}
        />
        <TextField label={t("blogPosts.excerpt")} value={form.excerpt} onChange={set("excerpt")} />
        <div className="flex flex-col gap-1">
          <label htmlFor={bodyId} className="text-sm font-medium">
            {t("blogPosts.body")}
          </label>
          <textarea
            id={bodyId}
            className="min-h-48 rounded-md border border-border bg-background p-2 text-sm"
            aria-describedby={`${bodyId}-hint`}
            value={form.body}
            onChange={set("body")}
          />
          <p id={`${bodyId}-hint`} className="text-xs text-muted-foreground">
            {t("blogPosts.bodyHint")}
          </p>
        </div>
        <TextField
          label={t("blogPosts.author")}
          value={form.author_name}
          onChange={set("author_name")}
        />
        <TextField
          label={t("blogPosts.seoTitle")}
          value={form.seo_title}
          onChange={set("seo_title")}
        />
        <TextField
          label={t("blogPosts.metaDescription")}
          value={form.meta_description}
          onChange={set("meta_description")}
        />
        {save.error ? <Alert tone="danger">{save.error.message}</Alert> : null}
        <div className="flex gap-2">
          <Button type="submit" loading={save.isPending}>
            {t("blogPosts.save")}
          </Button>
          <Button type="button" variant="secondary" onClick={onClose}>
            {t("blogPosts.cancel")}
          </Button>
        </div>
      </form>
    </Card>
  );
}
