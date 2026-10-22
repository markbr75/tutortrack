import { unwrap, type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Button, NamePlate, PanelRow, PanelRows, RuledPanel, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, usePermission } from "../api";
import { PanelEmpty, PanelLoading } from "../billing/moneyUi";
import { MutationError, QueryState } from "./shared";

type Subject = components["schemas"]["Subject"];

function AddLevel({ subject }: { subject: Subject }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const add = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/v1/catalogue/levels", { body: { subject: subject.id, name } })),
    onSuccess: () => {
      setName("");
      void queryClient.invalidateQueries({ queryKey: ["catalogue", "subjects"] });
    },
  });
  return (
    <form
      className="flex flex-wrap items-end gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (name.trim()) add.mutate();
      }}
    >
      <div className="min-w-56 flex-1 sm:max-w-sm">
        <TextField
          label={t("catalogue.subjects.newLevel", { subject: subject.name })}
          size="sm"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </div>
      <Button type="submit" variant="secondary" size="sm" className="h-9" loading={add.isPending}>
        {t("catalogue.add")}
      </Button>
      {add.error ? (
        <div className="w-full">
          <MutationError error={add.error} />
        </div>
      ) : null}
    </form>
  );
}

/** Subjects and levels (FR-06-1). */
export function SubjectsSection() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canManage = usePermission("catalogue.manage");
  const [name, setName] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const subjects = useQuery({
    queryKey: ["catalogue", "subjects"],
    queryFn: async () => unwrap(await api.GET("/api/v1/catalogue/subjects")),
  });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["catalogue", "subjects"] });
  const add = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/v1/catalogue/subjects", { body: { name } })),
    onSuccess: () => {
      setName("");
      refresh();
    },
  });
  const archive = useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.POST("/api/v1/catalogue/subjects/{id}/archive", { params: { path: { id } } }),
      ),
    onSuccess: refresh,
  });
  const rows = subjects.data ?? [];
  return (
    <QueryState query={subjects}>
      <RuledPanel
        flush
        title={t("catalogue.tabs.subjects")}
        aside={
          subjects.data ? (
            <span className="text-muted-foreground tabular-nums">
              {t("designS6.catalogue.subjectCount", { count: rows.length })}
            </span>
          ) : null
        }
        footer={
          canManage ? (
            <form
              className="flex w-full flex-wrap items-end gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                if (name.trim()) add.mutate();
              }}
            >
              <div className="min-w-56 flex-1 sm:max-w-sm">
                <TextField
                  label={t("catalogue.subjects.new")}
                  size="sm"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </div>
              <Button
                type="submit"
                variant="secondary"
                size="sm"
                className="h-9"
                loading={add.isPending}
              >
                {t("catalogue.add")}
              </Button>
              {add.error ? (
                <div className="w-full">
                  <MutationError error={add.error} />
                </div>
              ) : null}
            </form>
          ) : null
        }
      >
        {subjects.isPending ? (
          <PanelLoading label={t("grid.loading")} />
        ) : !rows.length ? (
          <PanelEmpty>{t("designS6.catalogue.noSubjects")}</PanelEmpty>
        ) : (
          <PanelRows>
            {rows.map((subject) => (
              <PanelRow key={subject.id}>
                <NamePlate
                  name={subject.name}
                  context={
                    (subject.levels.map((l) => l.name).join(", ") ||
                      t("catalogue.subjects.noLevels")) +
                    (subject.exam_boards?.length ? ` · ${subject.exam_boards.join(", ")}` : "")
                  }
                  aside={
                    canManage ? (
                      <>
                        <Button
                          size="sm"
                          variant="secondary"
                          aria-expanded={open === subject.id}
                          onClick={() => setOpen(open === subject.id ? null : subject.id)}
                        >
                          {t("catalogue.subjects.addLevel")}
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          className="text-muted-foreground"
                          aria-label={t("catalogue.archiveNamed", { name: subject.name })}
                          onClick={() => archive.mutate(subject.id)}
                        >
                          {t("catalogue.archive")}
                        </Button>
                      </>
                    ) : null
                  }
                />
                {open === subject.id ? (
                  <div className="mt-3">
                    <AddLevel subject={subject} />
                  </div>
                ) : null}
              </PanelRow>
            ))}
          </PanelRows>
        )}
      </RuledPanel>
    </QueryState>
  );
}
