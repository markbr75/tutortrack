import { unwrap } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Button, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { api } from "../api";
import { ErrorList } from "../calendar/ErrorList";

type Audience = "clients" | "tutors" | "everyone";

/** News posts shown in the family and tutor portals (E15-T07). */
export function AnnouncementsPage() {
  const { t, i18n } = useTranslation();
  const bodyId = useId();
  const queryClient = useQueryClient();
  const [form, setForm] = useState({ title: "", body: "", audience: "everyone" as Audience });
  const list = useQuery({
    queryKey: ["announcements"],
    queryFn: async () => unwrap(await api.GET("/api/v1/announcements")),
  });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["announcements"] });
  const create = useMutation({
    mutationFn: async () => unwrap(await api.POST("/api/v1/announcements", { body: form })),
    onSuccess: () => {
      setForm({ title: "", body: "", audience: "everyone" });
      refresh();
    },
  });
  const remove = useMutation({
    mutationFn: async (id: string) =>
      api.DELETE("/api/v1/announcements/{id}", { params: { path: { id } } }),
    onSuccess: refresh,
  });
  return (
    <div className="max-w-2xl space-y-4">
      <h1 className="text-2xl font-semibold">{t("announcements.title")}</h1>
      <form
        className="space-y-2"
        aria-label={t("announcements.new")}
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate();
        }}
      >
        <TextField
          label={t("announcements.heading")}
          required
          value={form.title}
          onChange={(e) => setForm({ ...form, title: e.target.value })}
        />
        <div className="space-y-1">
          <label htmlFor={bodyId} className="text-sm font-medium">
            {t("announcements.body")}
          </label>
          <textarea
            id={bodyId}
            required
            className="min-h-24 w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
            value={form.body}
            onChange={(e) => setForm({ ...form, body: e.target.value })}
          />
        </div>
        <SelectField
          label={t("announcements.audience")}
          value={form.audience}
          onChange={(e) => setForm({ ...form, audience: e.target.value as Audience })}
          options={(["everyone", "clients", "tutors"] as const).map((a) => ({
            value: a,
            label: t(`announcements.audiences.${a}`),
          }))}
        />
        <ErrorList error={create.error} />
        <Button type="submit" disabled={create.isPending}>
          {t("announcements.publish")}
        </Button>
      </form>
      {list.isPending ? (
        <Spinner className="size-5" label={t("grid.loading")} />
      ) : (
        <ul className="space-y-2">
          {(list.data?.results ?? []).map((a) => (
            <li key={a.id} className="rounded-md border border-border p-3">
              <p className="font-medium">{a.title}</p>
              <p className="text-xs text-muted-foreground">
                {t(`announcements.audiences.${a.audience}`)} ·{" "}
                {a.published_at ? formatDateTime(a.published_at, i18n.language) : ""}
              </p>
              <p className="whitespace-pre-wrap text-sm">{a.body}</p>
              <Button size="sm" variant="ghost" onClick={() => remove.mutate(a.id)}>
                {t("announcements.delete")}
                <span className="sr-only"> {a.title}</span>
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
