import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { api, usePermission } from "../api";
import { uploadFile } from "../learning/hooks";
import type { TargetRef } from "./Activity";

type DocumentRow = components["schemas"]["Document"];
type Category = components["schemas"]["DocumentCategoryEnum"];

const CATEGORIES: Category[] = ["contract", "consent_form", "report", "id", "other"];
/** Records whose people can sign in a portal (families, students and tutors). */
const SIGNABLE = new Set(["people.client", "people.student", "people.tutor"]);

async function openFile(id: string) {
  const link = unwrap(await api.GET("/api/v1/files/{id}/download", { params: { path: { id } } }));
  window.location.assign(link.url);
}

function Signatures({ document }: { document: DocumentRow }) {
  const { t, i18n } = useTranslation();
  const trail = useQuery({
    queryKey: ["document-signatures", document.id],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/documents/{id}/signatures", {
          params: { path: { id: document.id } },
        }),
      ),
  });
  if (trail.isPending) return <Spinner />;
  return (
    <ul className="mt-2 divide-y divide-rule rounded-md border border-border bg-background text-sm">
      {(trail.data ?? []).map((s) => (
        <li key={s.id} className="space-y-0.5 px-3 py-2">
          <p>
            {t("esign.signedBy", {
              name: s.signer_name,
              when: formatDateTime(s.signed_at, i18n.language),
            })}
          </p>
          <p className="text-xs text-muted-foreground">
            {t("esign.trail", { ip: s.ip ?? "-", agent: s.user_agent || "-" })}
          </p>
          <p className="text-xs break-all text-muted-foreground">
            {t("esign.hash", { hash: s.content_sha256 })}
          </p>
          {s.signed_file ? (
            <Button
              size="sm"
              variant="secondary"
              className="mt-1"
              onClick={() => void openFile(s.signed_file as string)}
            >
              {t("esign.signedCopy")}
            </Button>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

/** Documents on a record (FR-05-9) with click-to-sign requests (gap batch G2). */
export function Documents({ target }: { target: TargetRef }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const canCreate = usePermission("crm.document.create");
  const signable = SIGNABLE.has(target.target_type);
  const fileId = useId();
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState<Category>("contract");
  const [sign, setSign] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const key = ["documents", target];
  const documents = useQuery({
    queryKey: key,
    queryFn: async () => unwrap(await api.GET("/api/v1/documents", { params: { query: target } })),
  });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: key });
  const add = useMutation({
    mutationFn: async () => {
      if (!file) return;
      const id = await uploadFile(file);
      unwrap(
        await api.POST("/api/v1/documents", {
          body: {
            ...target,
            file: id,
            title: title || file.name,
            category,
            signature_required: signable && sign,
          },
        }),
      );
    },
    onSuccess: () => {
      setFile(null);
      setTitle("");
      setSign(false);
      refresh();
    },
  });
  const request = useMutation({
    mutationFn: async ({ id, required }: { id: string; required: boolean }) =>
      unwrap(
        await api.POST("/api/v1/documents/{id}/request-signature", {
          params: { path: { id } },
          body: { signature_required: required },
        }),
      ),
    onSuccess: refresh,
  });
  const rows = documents.data?.results ?? [];
  return (
    <div className="space-y-4">
      {canCreate ? (
        <form
          className="grid gap-3 sm:grid-cols-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (file) add.mutate();
          }}
        >
          <div>
            <label htmlFor={fileId} className="mb-1 block text-sm font-medium">
              {t("esign.file")}
            </label>
            <input
              id={fileId}
              type="file"
              className="block w-full text-sm file:mr-3 file:h-8 file:rounded-md file:border file:border-border file:bg-surface file:px-3 file:text-sm file:font-medium file:text-foreground hover:file:bg-muted"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
          </div>
          <TextField
            label={t("esign.title")}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
          <SelectField
            label={t("esign.category")}
            value={category}
            options={CATEGORIES.map((c) => ({ value: c, label: t(`esign.categories.${c}`) }))}
            onChange={(e) => setCategory(e.target.value as Category)}
          />
          {signable ? (
            <label className="flex items-center gap-2 self-end text-sm">
              <input type="checkbox" checked={sign} onChange={(e) => setSign(e.target.checked)} />
              {t("esign.askToSign")}
            </label>
          ) : null}
          {add.isError ? <Alert tone="danger">{add.error.message}</Alert> : null}
          <div>
            <Button type="submit" loading={add.isPending} disabled={!file}>
              {t("esign.upload")}
            </Button>
          </div>
        </form>
      ) : null}
      {documents.isPending ? <Spinner /> : null}
      {!documents.isPending && rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("esign.none")}</p>
      ) : null}
      {rows.length ? (
      <ul className="divide-y divide-rule border-t border-rule">
        {rows.map((d) => (
          <li key={d.id} className="py-2.5 text-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="min-w-0">
                <p className="font-medium">{d.title}</p>
                <p className="text-xs text-muted-foreground">
                  {t(`esign.categories.${d.category ?? "other"}`)} ·{" "}
                  {formatDateTime(d.created_at, i18n.language)} ·{" "}
                  {t(`esign.status.${d.signature_status}`)}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="secondary" onClick={() => void openFile(d.file)}>
                  {t("esign.download", { title: d.title })}
                </Button>
                {canCreate && signable && d.signature_status === "not_required" ? (
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => request.mutate({ id: d.id, required: true })}
                  >
                    {t("esign.requestSignature")}
                  </Button>
                ) : null}
                {canCreate && d.signature_status === "awaiting" ? (
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => request.mutate({ id: d.id, required: false })}
                  >
                    {t("esign.cancelRequest")}
                  </Button>
                ) : null}
                {d.signature_status === "signed" ? (
                  <Button
                    size="sm"
                    variant="secondary"
                    aria-expanded={open === d.id}
                    onClick={() => setOpen(open === d.id ? null : d.id)}
                  >
                    {t("esign.auditTrail")}
                  </Button>
                ) : null}
              </div>
            </div>
            {open === d.id ? <Signatures document={d} /> : null}
          </li>
        ))}
      </ul>
      ) : null}
      {request.isError ? <Alert tone="danger">{request.error.message}</Alert> : null}
    </div>
  );
}
