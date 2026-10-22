import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  NamePlate,
  PanelFooter,
  PanelRows,
  RuledPanel,
  Spinner,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { api, usePermission } from "../api";

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
    <div className="max-w-4xl space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
        <p className="max-w-2xl text-sm text-muted-foreground">{t("blogPosts.intro")}</p>
        {canManage && !editing ? (
          <Button onClick={() => setEditing("new")}>{t("blogPosts.new")}</Button>
        ) : null}
      </div>
      {editing ? (
        <PostEditor
          key={editing === "new" ? "new" : editing.id}
          post={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
        />
      ) : null}
      {posts.isPending ? (
        <Spinner label={t("grid.loading")} />
      ) : (
        <RuledPanel title={t("blogPosts.tab")} flush>
          {posts.data?.results.length ? (
            <PanelRows>
              {posts.data.results.map((post) => (
                <PostRow key={post.id} post={post} onEdit={() => setEditing(post)} />
              ))}
            </PanelRows>
          ) : (
            <p className="px-5 py-4 text-sm text-muted-foreground">{t("blogPosts.none")}</p>
          )}
        </RuledPanel>
      )}
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
    <li className="px-5 py-2.5 text-sm">
      <NamePlate
        name={post.title}
        context={
          <>
            <span className={post.status === "published" ? undefined : "text-foreground"}>
              {t(`blogPosts.status.${post.status}`)}
            </span>
            {post.published_at ? (
              <span className="tabular-nums"> · {formatDateTime(post.published_at)}</span>
            ) : null}{" "}
            · <span className="break-all">{post.url}</span>
          </>
        }
        aside={
          <>
            <Button size="sm" variant="secondary" onClick={onEdit}>
              {t("blogPosts.edit")}
            </Button>
            {canPublish ? (
              <Button
                size="sm"
                variant={post.status === "published" ? "ghost" : "secondary"}
                loading={toggle.isPending}
                onClick={() => toggle.mutate()}
              >
                {post.status === "published" ? t("blogPosts.unpublish") : t("blogPosts.publish")}
              </Button>
            ) : null}
          </>
        }
      />
      {toggle.error ? (
        <Alert tone="danger" className="mt-2">
          {toggle.error.message}
        </Alert>
      ) : null}
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
    <RuledPanel title={post ? t("blogPosts.editTitle") : t("blogPosts.new")} flush>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
      >
        <div className="space-y-4 px-5 py-4">
          <div className="grid gap-4 sm:grid-cols-2">
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
          </div>
          <TextField
            label={t("blogPosts.excerpt")}
            value={form.excerpt}
            onChange={set("excerpt")}
          />
          <div className="flex flex-col gap-1">
            <label htmlFor={bodyId} className="text-sm font-medium">
              {t("blogPosts.body")}
            </label>
            <textarea
              id={bodyId}
              className="min-h-48 rounded-md border border-field bg-surface px-3 py-2 text-sm"
              aria-describedby={`${bodyId}-hint`}
              value={form.body}
              onChange={set("body")}
            />
            <p id={`${bodyId}-hint`} className="text-xs text-muted-foreground">
              {t("blogPosts.bodyHint")}
            </p>
          </div>
          <div className="grid gap-4 sm:grid-cols-3">
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
          </div>
          {save.error ? <Alert tone="danger">{save.error.message}</Alert> : null}
        </div>
        <PanelFooter>
          <Button type="submit" size="sm" loading={save.isPending}>
            {t("blogPosts.save")}
          </Button>
          <Button type="button" size="sm" variant="ghost" onClick={onClose}>
            {t("blogPosts.cancel")}
          </Button>
        </PanelFooter>
      </form>
    </RuledPanel>
  );
}
