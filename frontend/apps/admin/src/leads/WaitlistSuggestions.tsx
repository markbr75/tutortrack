import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api";

type Suggestion = components["schemas"]["WaitlistSuggestion"];

/** Tutors who now have room for waiting students (gap G5c, FR-17-6). Raised when tutor
 * capacity appears; staff offer the place from here (the family gets the time-limited
 * offer link) or dismiss the suggestion. */
export function WaitlistSuggestions() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [details, setDetails] = useState<Record<string, string>>({});
  const suggestions = useQuery({
    queryKey: ["waitlist-suggestions"],
    queryFn: async () => unwrap(await api.GET("/api/v1/waitlist-suggestions")),
  });
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["waitlist-suggestions"] });
    void queryClient.invalidateQueries({ queryKey: ["waitlist"] });
  };
  const offer = useMutation({
    mutationFn: async (s: Suggestion) =>
      unwrap(
        await api.POST("/api/v1/waitlist-suggestions/{id}/offer", {
          params: { path: { id: s.id } },
          body: { details: details[s.id] ?? "" },
        }),
      ),
    onSuccess: refresh,
  });
  const dismiss = useMutation({
    mutationFn: async (s: Suggestion) =>
      unwrap(
        await api.POST("/api/v1/waitlist-suggestions/{id}/dismiss", {
          params: { path: { id: s.id } },
        }),
      ),
    onSuccess: refresh,
  });
  const rows = suggestions.data?.results ?? [];
  if (!rows.length) return null;
  return (
    <section aria-labelledby="waitlist-suggestions" className="space-y-2">
      <h2 id="waitlist-suggestions" className="text-base font-semibold">
        {t("g5c.suggestions.title", { count: rows.length })}
      </h2>
      <p className="text-sm text-muted-foreground">{t("g5c.suggestions.intro")}</p>
      <ul className="divide-y divide-rule rounded-xl border border-border bg-surface">
        {rows.map((s) => (
          <li key={s.id} className="flex flex-wrap items-end gap-3 px-5 py-2.5 text-sm">
            <div className="min-w-56 flex-1">
              <p className="font-medium">
                {t("g5c.suggestions.room", { tutor: s.tutor_name, student: s.student_name })}
              </p>
              <p className="text-xs text-muted-foreground">
                {[
                  s.position ? `#${s.position}` : "",
                  s.subject,
                  t(`g5c.suggestions.reasons.${s.reason}`),
                  s.score ? t("g5c.suggestions.score", { score: s.score }) : "",
                  formatDate(s.created_at),
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
            </div>
            <TextField
              label={t("g5c.suggestions.details", { student: s.student_name })}
              hint={t("g5c.suggestions.detailsHint")}
              value={details[s.id] ?? ""}
              onChange={(e) => setDetails({ ...details, [s.id]: e.target.value })}
            />
            <div className="flex gap-2">
              <Button
                size="sm"
                disabled={offer.isPending}
                onClick={() => offer.mutate(s)}
                aria-label={t("g5c.suggestions.offerTo", {
                  student: s.student_name,
                  tutor: s.tutor_name,
                })}
              >
                {t("g5c.suggestions.offer")}
              </Button>
              <Button
                size="sm"
                variant="secondary"
                disabled={dismiss.isPending}
                onClick={() => dismiss.mutate(s)}
                aria-label={t("g5c.suggestions.dismissFor", {
                  student: s.student_name,
                  tutor: s.tutor_name,
                })}
              >
                {t("g5c.suggestions.dismiss")}
              </Button>
            </div>
          </li>
        ))}
      </ul>
      {offer.error ? <Alert tone="danger">{offer.error.message}</Alert> : null}
      {dismiss.error ? <Alert tone="danger">{dismiss.error.message}</Alert> : null}
    </section>
  );
}
