import { unwrap } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Button, Spinner } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { api } from "../api";

function Reply({ reportId }: { reportId: string }) {
  const { t } = useTranslation();
  const id = useId();
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
      className="space-y-1"
      onSubmit={(e) => {
        e.preventDefault();
        if (body.trim()) send.mutate();
      }}
    >
      <label htmlFor={id} className="text-sm font-medium">
        {t("portal.reply")}
      </label>
      <textarea
        id={id}
        className="w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
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
              className="underline underline-offset-2"
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

/** Shared lesson reports (only the fields families may see) with replies (FR-15-6). */
export function ReportsPage() {
  const { t, i18n } = useTranslation();
  const reports = useQuery({
    queryKey: ["portal", "reports"],
    queryFn: async () => unwrap(await api.GET("/api/v1/portal/reports")),
  });
  if (reports.isPending) return <Spinner className="size-6" label={t("grid.loading")} />;
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">{t("portal.nav.reports")}</h1>
      {!reports.data?.length ? (
        <p className="text-sm text-muted-foreground">{t("portal.noReports")}</p>
      ) : null}
      {reports.data?.map((r) => (
        <article
          key={r.id}
          className="space-y-3 rounded-lg border border-border p-4"
          aria-label={r.lesson_title}
        >
          <header>
            <h2 className="font-semibold">{r.lesson_title}</h2>
            <p className="text-sm text-muted-foreground">
              {formatDateTime(r.lesson_start, i18n.language)} · {r.tutor_name}
            </p>
          </header>
          <dl className="space-y-2">
            {r.answers.map((a) => (
              <div key={a.label}>
                <dt className="text-sm font-medium">{a.label}</dt>
                <dd className="whitespace-pre-wrap text-sm">
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
            <ul className="space-y-1 border-t border-border pt-2 text-sm">
              {r.comments.map((c, i) => (
                <li key={i}>
                  <strong>{c.author}:</strong> {c.body}
                </li>
              ))}
            </ul>
          ) : null}
          <Reply reportId={r.id} />
        </article>
      ))}
    </div>
  );
}
