import { unwrap } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Button, Spinner, TextAreaField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api";
import { PortalHeader } from "../layout/PortalPage";

function Reply({ reportId }: { reportId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [body, setBody] = useState("");
  const send = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/portal/reports/{report_id}/comments", {
          params: { path: { report_id: reportId } },
          body: { body },
        }),
      ),
    onSuccess: () => {
      setBody("");
      void queryClient.invalidateQueries({ queryKey: ["portal", "reports"] });
    },
  });
  return (
    <form
      className="space-y-3 border-t border-border px-5 py-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (body.trim()) send.mutate();
      }}
    >
      <TextAreaField
        label={t("portal.reply")}
        rows={2}
        value={body}
        onChange={(e) => setBody(e.target.value)}
      />
      <Button type="submit" size="sm" disabled={send.isPending}>
        {t("portal.sendReply")}
      </Button>
    </form>
  );
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Files attached to a shared report (gap G3): download links (scanned files only). */
function ReportFiles({ ids }: { ids: string[] }) {
  const { t } = useTranslation();
  const open = async (id: string) => {
    const link = unwrap(await api.GET("/api/v1/files/{id}/download", { params: { path: { id } } }));
    window.open(link.url, "_blank", "noopener");
  };
  return (
    <ul className="space-y-1">
      {ids.map((id, n) =>
        UUID.test(id) ? (
          <li key={id}>
            <button
              type="button"
              className="font-medium text-link underline-offset-2 hover:underline"
              onClick={() => void open(id)}
            >
              {t("g3.files.attachment", { n: n + 1 })}
            </button>
          </li>
        ) : (
          <li key={id}>{id}</li>
        ),
      )}
    </ul>
  );
}

function show(value: unknown): string {
  return Array.isArray(value) ? value.join(", ") : String(value ?? "");
}

/** Shared lesson reports (only the fields families may see) with replies (FR-15-6). Each
 * report is one ruled leaf: the lesson and when, the answers as ruled rows, the replies, and
 * the reply form under a register rule. */
export function ReportsPage() {
  const { t, i18n } = useTranslation();
  const reports = useQuery({
    queryKey: ["portal", "reports"],
    queryFn: async () => unwrap(await api.GET("/api/v1/portal/reports")),
  });
  if (reports.isPending) return <Spinner label={t("grid.loading")} />;
  return (
    <div>
      <PortalHeader title={t("portal.nav.reports")} />
      {!reports.data?.length ? (
        <p className="text-sm text-muted-foreground">{t("portal.noReports")}</p>
      ) : null}
      <div className="space-y-6">
        {reports.data?.map((r) => (
          <article
            key={r.id}
            className="rounded-xl border border-border bg-surface"
            aria-label={r.lesson_title}
          >
            <header className="border-b border-border px-5 py-3.5">
              <h2 className="text-base font-semibold">{r.lesson_title}</h2>
              <p className="text-xs text-muted-foreground tabular-nums">
                {formatDateTime(r.lesson_start, i18n.language)} · {r.tutor_name}
              </p>
            </header>
            <dl className="divide-y divide-rule">
              {r.answers.map((a) => (
                <div key={a.label} className="space-y-0.5 px-5 py-2.5">
                  <dt className="text-xs font-semibold text-muted-foreground">{a.label}</dt>
                  <dd className="text-sm whitespace-pre-wrap">
                    {a.type === "attachment" && Array.isArray(a.value) ? (
                      <ReportFiles ids={a.value as string[]} />
                    ) : (
                      show(a.value)
                    )}
                  </dd>
                </div>
              ))}
            </dl>
            {r.comments.length ? (
              <ul
                aria-label={t("designS10.replies")}
                className="divide-y divide-rule border-t border-border"
              >
                {r.comments.map((c, i) => (
                  <li key={i} className="px-5 py-2.5 text-sm">
                    <p className="text-xs font-medium">{c.author}</p>
                    <p className="whitespace-pre-wrap">{c.body}</p>
                  </li>
                ))}
              </ul>
            ) : null}
            <Reply reportId={r.id} />
          </article>
        ))}
      </div>
    </div>
  );
}
