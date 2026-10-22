import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  PanelFooter,
  PanelRow,
  PanelRows,
  RuledPanel,
  Spinner,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check } from "lucide-react";
import { useState } from "react";

import { api, uploadFile } from "../api";
import { SignForm } from "../esign/SignForm";
import { FileField, PanelEmpty, PortalHeader, Word } from "../layout/PortalPage";
import { DocumentList } from "../pages/DocumentsPage";
import { MyBackgroundChecks } from "./Phase3";

/** The onboarding checklist (FR-18-5): one ruled row per step, its state or action on the
 * right; signing opens in place under the step. */
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
  const [signing, setSigning] = useState<string | null>(null);
  const sign = useMutation({
    mutationFn: async ({ key, name }: { key: string; name: string }) =>
      unwrap(
        await api.POST("/api/v1/me/onboarding/{key}/sign", {
          params: { path: { key } },
          body: { full_name: name, agree: true },
        }),
      ),
    onSuccess: (data) => {
      setSigning(null);
      queryClient.setQueryData(["tutor", "onboarding"], data);
    },
  });
  if (!state.data) return <Spinner label={t("grid.loading")} />;
  const items = state.data.items;
  const done = items.filter((item) => item.done).length;
  return (
    <div>
      <PortalHeader title={t("onboard.title")} />
      <div className="space-y-6">
        {state.data.completed_at ? <Alert tone="success">{t("onboard.complete")}</Alert> : null}
        <RuledPanel
          title={t("designS10.steps")}
          aside={
            items.length ? (
              <span className="text-muted-foreground tabular-nums">
                {t("designS10.doneOf", { done, total: items.length })}
              </span>
            ) : undefined
          }
          flush
        >
          {items.length ? null : <PanelEmpty>{t("designS10.noSteps")}</PanelEmpty>}
          <PanelRows>
            {items.map((item) => (
              <PanelRow key={item.key}>
                <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
                  <span className="min-w-0">
                    <span className="font-medium">{item.label}</span>
                    {item.mandatory ? (
                      <span className="block text-xs text-muted-foreground">
                        {t("designS10.required")}
                      </span>
                    ) : null}
                  </span>
                  {item.done ? (
                    <span className="flex items-center gap-1.5 font-medium">
                      <Check aria-hidden="true" className="size-4" strokeWidth={2.2} />
                      {item.signature_id ? t("esign.signedDone") : t("onboard.done")}
                    </span>
                  ) : item.needs_signature ? (
                    signing === item.key ? null : (
                      <Button size="sm" onClick={() => setSigning(item.key)}>
                        {t("esign.signButton", { title: item.label })}
                      </Button>
                    )
                  ) : ["agreement", "training", "custom"].includes(item.kind) ? (
                    <Button size="sm" variant="secondary" onClick={() => tick.mutate(item.key)}>
                      {t("onboard.markDone")}
                    </Button>
                  ) : (
                    <span className="text-xs text-muted-foreground">{t("onboard.auto")}</span>
                  )}
                </div>
                {signing === item.key ? (
                  <div className="mt-2">
                    {item.link ? (
                      <a
                        className="text-sm font-medium text-link underline-offset-2 hover:underline"
                        href={item.link}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {t("esign.read", { title: item.label })}
                      </a>
                    ) : null}
                    <SignForm
                      title={item.label}
                      pending={sign.isPending}
                      error={sign.error?.message}
                      onSign={(name) => sign.mutate({ key: item.key, name })}
                      onCancel={() => setSigning(null)}
                    />
                  </div>
                ) : null}
              </PanelRow>
            ))}
          </PanelRows>
          {tick.error ? (
            <div className="px-5 pb-4">
              <Alert tone="danger">{tick.error.message}</Alert>
            </div>
          ) : null}
        </RuledPanel>
        <RuledPanel title={t("esign.tutorTitle")} titleId="tutor-documents" flush>
          <DocumentList
            queryKey={["tutor", "documents"]}
            list={async () => unwrap(await api.GET("/api/v1/tutor/documents"))}
            download={async (id) =>
              unwrap(
                await api.GET("/api/v1/tutor/documents/{document_id}/download", {
                  params: { path: { document_id: id } },
                }),
              )
            }
            sign={async (id, fullName) =>
              unwrap(
                await api.POST("/api/v1/tutor/documents/{document_id}/sign", {
                  params: { path: { document_id: id } },
                  body: { full_name: fullName, agree: true },
                }),
              )
            }
          />
        </RuledPanel>
      </div>
    </div>
  );
}

type Requirement = components["schemas"]["RequirementType"];

/** The tutor's checks (FR-18-6): one ruled panel, a row per check with its status in words
 * and a small "Add details" that opens that check's form in place, one at a time. */
export function ChecksPage() {
  const { t } = useTranslation();
  const [open, setOpen] = useState<string | null>(null);
  const data = useQuery({
    queryKey: ["tutor", "compliance"],
    queryFn: async () => unwrap(await api.GET("/api/v1/me/compliance")),
  });
  if (!data.data) return <Spinner label={t("grid.loading")} />;
  const records = new Map(data.data.records.map((r) => [r.requirement, r]));
  const requirements = data.data.requirements;
  return (
    <div>
      <PortalHeader title={t("onboard.checksTitle")} />
      <div className="space-y-6">
        {data.data.restricted ? <Alert tone="warning">{t("onboard.restricted")}</Alert> : null}
        <MyBackgroundChecks />
        <RuledPanel label={t("onboard.checksTitle")} flush>
          {requirements.length ? (
            <ul className="divide-y divide-rule">
              {requirements.map((req) => (
                <CheckRow
                  key={req.id}
                  requirement={req}
                  record={records.get(req.id)}
                  open={open === req.id}
                  onOpen={() => setOpen(req.id)}
                  onClose={() => setOpen(null)}
                />
              ))}
            </ul>
          ) : (
            <PanelEmpty>{t("designS10.noChecks")}</PanelEmpty>
          )}
        </RuledPanel>
      </div>
    </div>
  );
}

function CheckRow({
  requirement,
  record,
  open,
  onOpen,
  onClose,
}: {
  requirement: Requirement;
  record?: components["schemas"]["ComplianceRecord"];
  open: boolean;
  onOpen: () => void;
  onClose: () => void;
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
    onSuccess: (data) => {
      queryClient.setQueryData(["tutor", "compliance"], data);
      onClose();
    },
  });
  const needsDetails = status !== "verified" || !record?.valid;
  return (
    <li>
      <div className="flex items-center gap-x-3 px-5 py-2.5 text-sm">
        <div className="min-w-0 flex-1">
          <p className="font-medium">{requirement.name}</p>
          {record?.expiry_date || record?.rejection_reason ? (
            <p className="text-xs text-muted-foreground tabular-nums">
              {record?.expiry_date
                ? `${t("onboard.expiryDate")}: ${formatDate(record.expiry_date, i18n.language)}`
                : ""}
              {record?.expiry_date && record?.rejection_reason ? " · " : ""}
              {record?.rejection_reason ? (
                <span className="text-danger">{record.rejection_reason}</span>
              ) : null}
            </p>
          ) : null}
        </div>
        <div className="flex shrink-0 items-center gap-3">
          <Word tone={status === "submitted" ? "muted" : "ink"} className="font-medium">
            {t(`onboard.status.${status}`)}
          </Word>
          {needsDetails && !open ? (
            <Button size="sm" variant="secondary" onClick={onOpen}>
              {t("designS10.addDetails")}
              <span className="sr-only"> {requirement.name}</span>
            </Button>
          ) : null}
        </div>
      </div>
      {open ? (
        <form
          aria-label={requirement.name}
          className="border-t border-rule"
          onSubmit={(e) => {
            e.preventDefault();
            submit.mutate();
          }}
          onKeyDown={(e) => {
            if (e.key === "Escape") onClose();
          }}
        >
          <div className="grid items-start gap-x-4 gap-y-3 px-5 py-4 sm:grid-cols-2">
            {requirement.has_number ? (
              <TextField
                autoFocus
                label={t("onboard.number")}
                className="tabular-nums"
                value={number}
                onChange={(e) => setNumber(e.target.value)}
              />
            ) : null}
            <TextField
              autoFocus={!requirement.has_number}
              label={t("onboard.issueDate")}
              className="tabular-nums"
              type="date"
              value={issue}
              onChange={(e) => setIssue(e.target.value)}
            />
            {requirement.has_expiry ? (
              <TextField
                label={t("onboard.expiryDate")}
                className="tabular-nums"
                type="date"
                value={expiry}
                onChange={(e) => setExpiry(e.target.value)}
              />
            ) : null}
            <FileField
              label={t("onboard.file")}
              accept="image/*,application/pdf"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </div>
          {submit.error ? (
            <div className="px-5 pb-4">
              <Alert tone="danger">{submit.error.message}</Alert>
            </div>
          ) : null}
          <PanelFooter>
            <Button type="submit" disabled={submit.isPending}>
              {t("onboard.upload")}
            </Button>
            <Button
              type="button"
              variant="ghost"
              className="text-muted-foreground hover:text-foreground"
              onClick={onClose}
            >
              {t("common.cancel")}
            </Button>
          </PanelFooter>
        </form>
      ) : null}
    </li>
  );
}
