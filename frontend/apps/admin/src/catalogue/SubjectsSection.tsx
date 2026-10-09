import { unwrap, type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Button, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, usePermission } from "../api";
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
      <TextField
        label={t("catalogue.subjects.newLevel", { subject: subject.name })}
        value={name}
        onChange={(e) => setName(e.target.value)}
      />
      <Button type="submit" variant="secondary" size="sm" disabled={add.isPending}>
        {t("catalogue.add")}
      </Button>
      <MutationError error={add.error} />
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
  return (
    <div className="space-y-6">
      {canManage ? (
        <form
          className="flex flex-wrap items-end gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (name.trim()) add.mutate();
          }}
        >
          <TextField
            label={t("catalogue.subjects.new")}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <Button type="submit" disabled={add.isPending}>
            {t("catalogue.add")}
          </Button>
          <MutationError error={add.error} />
        </form>
      ) : null}
      <QueryState query={subjects}>
        <ul className="divide-y divide-border rounded-md border border-border">
          {(subjects.data ?? []).map((subject) => (
            <li key={subject.id} className="p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <p className="font-medium">{subject.name}</p>
                  <p className="text-sm text-muted-foreground">
                    {subject.levels.map((l) => l.name).join(", ") ||
                      t("catalogue.subjects.noLevels")}
                    {subject.exam_boards?.length ? ` · ${subject.exam_boards.join(", ")}` : ""}
                  </p>
                </div>
                {canManage ? (
                  <div className="flex gap-2">
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
                      aria-label={t("catalogue.archiveNamed", { name: subject.name })}
                      onClick={() => archive.mutate(subject.id)}
                    >
                      {t("catalogue.archive")}
                    </Button>
                  </div>
                ) : null}
              </div>
              {open === subject.id ? (
                <div className="mt-3">
                  <AddLevel subject={subject} />
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      </QueryState>
    </div>
  );
}
