import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, uploadFile } from "../api";

/** The onboarding checklist (FR-18-5). */
export function OnboardingPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const state = useQuery({
    queryKey: ["tutor", "onboarding"],
    queryFn: async () => unwrap(await api.GET("/api/v1/me/onboarding")),
  });
  const tick = useMutation({
    mutationFn: async (key: string) =>
      unwrap(await api.POST("/api/v1/me/onboarding/{key}/done", { params: { path: { key } } })),
    onSuccess: (data) => queryClient.setQueryData(["tutor", "onboarding"], data),
  });
  if (!state.data) return <Spinner className="size-5" label={t("grid.loading")} />;
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">{t("onboard.title")}</h1>
      {state.data.completed_at ? <Alert tone="success">{t("onboard.complete")}</Alert> : null}
      <ul className="divide-y divide-border rounded-lg border border-border text-sm">
        {state.data.items.map((item) => (
          <li key={item.key} className="flex flex-wrap items-center justify-between gap-2 p-3">
            <span>
              {item.label}
              {item.mandatory ? " *" : ""}
            </span>
            {item.done ? (
              <span className="font-medium">{t("onboard.done")}</span>
            ) : ["agreement", "training", "custom"].includes(item.kind) ? (
              <Button size="sm" variant="secondary" onClick={() => tick.mutate(item.key)}>
                {t("onboard.markDone")}
              </Button>
            ) : (
              <span className="text-xs text-muted-foreground">{t("onboard.auto")}</span>
            )}
          </li>
        ))}
      </ul>
      {tick.error ? <Alert tone="danger">{tick.error.message}</Alert> : null}
    </div>
  );
}

type Requirement = components["schemas"]["RequirementType"];

/** The tutor's checks: upload documents with numbers and dates (FR-18-6). */
export function ChecksPage() {
  const { t } = useTranslation();
  const data = useQuery({
    queryKey: ["tutor", "compliance"],
    queryFn: async () => unwrap(await api.GET("/api/v1/me/compliance")),
  });
  if (!data.data) return <Spinner className="size-5" label={t("grid.loading")} />;
  const records = new Map(data.data.records.map((r) => [r.requirement, r]));
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">{t("onboard.checksTitle")}</h1>
      {data.data.restricted ? <Alert tone="warning">{t("onboard.restricted")}</Alert> : null}
      <ul className="space-y-3">
        {data.data.requirements.map((req) => (
          <CheckItem key={req.id} requirement={req} record={records.get(req.id)} />
        ))}
      </ul>
    </div>
  );
}

function CheckItem({
  requirement,
  record,
}: {
  requirement: Requirement;
  record?: components["schemas"]["ComplianceRecord"];
}) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const [number, setNumber] = useState("");
  const [issue, setIssue] = useState("");
  const [expiry, setExpiry] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const status = record?.status ?? "missing";
  const submit = useMutation({
    mutationFn: async () => {
      const files = file ? [await uploadFile(file)] : undefined;
      return unwrap(
        await api.POST("/api/v1/me/compliance", {
          body: {
            requirement: requirement.id,
            number,
            issue_date: issue || null,
            expiry_date: expiry || null,
            notes: "",
            ...(files ? { files } : {}),
          },
        }),
      );
    },
    onSuccess: (data) => queryClient.setQueryData(["tutor", "compliance"], data),
  });
  return (
    <li className="space-y-2 rounded-lg border border-border p-3 text-sm">
      <p className="font-medium">
        {requirement.name}: {t(`onboard.status.${status}`)}
        {record?.expiry_date ? ` · ${formatDate(record.expiry_date, i18n.language)}` : ""}
      </p>
      {record?.rejection_reason ? <p className="text-danger">{record.rejection_reason}</p> : null}
      {status !== "verified" || !record?.valid ? (
        <form
          className="grid gap-2 sm:grid-cols-2"
          aria-label={requirement.name}
          onSubmit={(e) => {
            e.preventDefault();
            submit.mutate();
          }}
        >
          {requirement.has_number ? (
            <TextField
              label={t("onboard.number")}
              value={number}
              onChange={(e) => setNumber(e.target.value)}
            />
          ) : null}
          <TextField
            label={t("onboard.issueDate")}
            type="date"
            value={issue}
            onChange={(e) => setIssue(e.target.value)}
          />
          {requirement.has_expiry ? (
            <TextField
              label={t("onboard.expiryDate")}
              type="date"
              value={expiry}
              onChange={(e) => setExpiry(e.target.value)}
            />
          ) : null}
          <label className="flex flex-col gap-1">
            <span className="font-medium">{t("onboard.file")}</span>
            <input
              type="file"
              accept="image/*,application/pdf"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </label>
          <div className="sm:col-span-2">
            <Button type="submit" size="sm" disabled={submit.isPending}>
              {t("onboard.upload")}
            </Button>
          </div>
          {submit.error ? <Alert tone="danger">{submit.error.message}</Alert> : null}
        </form>
      ) : null}
    </li>
  );
}
