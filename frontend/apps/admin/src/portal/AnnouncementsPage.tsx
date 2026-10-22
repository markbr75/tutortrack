import { unwrap } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import {
  Button,
  FormPanel,
  NamePlate,
  PageHeader,
  PanelRow,
  PanelRows,
  RuledPanel,
  SelectField,
  Spinner,
  TextAreaField,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api";
import { ErrorList } from "../calendar/ErrorList";

type Audience = "clients" | "tutors" | "everyone";

/** News posts shown in the family and tutor portals (E15-T07). */
export function AnnouncementsPage() {
  const { t, i18n } = useTranslation();
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
  const posts = list.data?.results ?? [];
  return (
    <div className="max-w-3xl">
      <PageHeader
        title={t("announcements.title")}
        description={t("designS9b.announcements.description")}
      />
      <div className="space-y-6">
        <FormPanel
          title={t("announcements.new")}
          submit={t("announcements.publish")}
          pending={create.isPending}
          onSubmit={() => create.mutate()}
          error={create.error ? <ErrorList error={create.error} /> : null}
        >
          <TextField
            label={t("announcements.heading")}
            required
            value={form.title}
            onChange={(e) => setForm({ ...form, title: e.target.value })}
          />
          <SelectField
            label={t("announcements.audience")}
            value={form.audience}
            onChange={(e) => setForm({ ...form, audience: e.target.value as Audience })}
            options={(["everyone", "clients", "tutors"] as const).map((a) => ({
              value: a,
              label: t(`announcements.audiences.${a}`),
            }))}
          />
          <div className="sm:col-span-2">
            <TextAreaField
              label={t("announcements.body")}
              required
              rows={4}
              value={form.body}
              onChange={(e) => setForm({ ...form, body: e.target.value })}
            />
          </div>
        </FormPanel>
        <RuledPanel
          flush
          title={t("designS9b.announcements.published")}
          aside={
            list.data ? (
              <span className="text-muted-foreground tabular-nums">
                {t("designS9b.announcements.count", { count: posts.length })}
              </span>
            ) : null
          }
        >
          {list.isPending ? (
            <div className="px-5 py-4">
              <Spinner label={t("grid.loading")} />
            </div>
          ) : posts.length ? (
            <PanelRows>
              {posts.map((a) => (
                <PanelRow key={a.id} className="space-y-1.5">
                  <NamePlate
                    name={a.title}
                    context={
                      <span className="tabular-nums">
                        {t(`announcements.audiences.${a.audience}`)}
                        {a.published_at
                          ? ` · ${formatDateTime(a.published_at, i18n.language)}`
                          : ""}
                      </span>
                    }
                    aside={
                      <Button
                        size="sm"
                        variant="ghost"
                        className="text-muted-foreground"
                        onClick={() => remove.mutate(a.id)}
                      >
                        {t("announcements.delete")}
                        <span className="sr-only"> {a.title}</span>
                      </Button>
                    }
                  />
                  <p className="max-w-prose whitespace-pre-wrap">{a.body}</p>
                </PanelRow>
              ))}
            </PanelRows>
          ) : (
            <p className="px-5 py-4 text-sm text-muted-foreground">
              {t("designS9b.announcements.empty")}
            </p>
          )}
        </RuledPanel>
      </div>
    </div>
  );
}
