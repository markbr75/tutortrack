import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, Spinner } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api";
import { SignForm } from "../esign/SignForm";

type PortalDocument = components["schemas"]["PortalDocument"];

/** Documents shared with the family, and those waiting for a signature (FR-15-8). */
export function DocumentList({
  queryKey,
  list,
  download,
  sign,
}: {
  queryKey: readonly unknown[];
  list: () => Promise<PortalDocument[]>;
  download: (id: string) => Promise<{ url: string }>;
  sign: (id: string, fullName: string) => Promise<unknown>;
}) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const [signing, setSigning] = useState<string | null>(null);
  const documents = useQuery({ queryKey, queryFn: list });
  const open = useMutation({
    mutationFn: download,
    onSuccess: (data) => window.location.assign(data.url),
  });
  const signIt = useMutation({
    mutationFn: async ({ id, name }: { id: string; name: string }) => sign(id, name),
    onSuccess: () => {
      setSigning(null);
      void queryClient.invalidateQueries({ queryKey });
    },
  });
  if (documents.isPending) return <Spinner label={t("grid.loading")} />;
  const rows = documents.data ?? [];
  if (rows.length === 0) return <p className="text-sm text-muted-foreground">{t("esign.none")}</p>;
  return (
    <ul className="space-y-3">
      {rows.map((d) => (
        <li key={d.id} className="rounded-lg border border-border p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <p className="font-medium">{d.title}</p>
              <p className="text-sm text-muted-foreground">
                {d.signature_status === "signed" && d.signed_at
                  ? t("esign.signedOn", { when: formatDateTime(d.signed_at, i18n.language) })
                  : t(`esign.status.${d.signature_status}`)}
              </p>
            </div>
            <div className="flex gap-2">
              <Button size="sm" variant="secondary" onClick={() => open.mutate(d.id)}>
                {t("esign.download", { title: d.title })}
              </Button>
              {d.signature_status === "awaiting" && signing !== d.id ? (
                <Button size="sm" onClick={() => setSigning(d.id)}>
                  {t("esign.signButton", { title: d.title })}
                </Button>
              ) : null}
            </div>
          </div>
          {signing === d.id ? (
            <SignForm
              title={d.title}
              pending={signIt.isPending}
              error={signIt.error?.message}
              onSign={(name) => signIt.mutate({ id: d.id, name })}
              onCancel={() => setSigning(null)}
            />
          ) : null}
        </li>
      ))}
      {signIt.isSuccess ? (
        <li>
          <Alert tone="success">{t("esign.thanks")}</Alert>
        </li>
      ) : null}
    </ul>
  );
}

export function DocumentsPage() {
  const { t } = useTranslation();
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">{t("esign.portalTitle")}</h1>
      <DocumentList
        queryKey={["portal", "documents"]}
        list={async () => unwrap(await api.GET("/api/v1/portal/documents"))}
        download={async (id) =>
          unwrap(
            await api.GET("/api/v1/portal/documents/{document_id}/download", {
              params: { path: { document_id: id } },
            }),
          )
        }
        sign={async (id, fullName) =>
          unwrap(
            await api.POST("/api/v1/portal/documents/{document_id}/sign", {
              params: { path: { document_id: id } },
              body: { full_name: fullName, agree: true },
            }),
          )
        }
      />
    </div>
  );
}
