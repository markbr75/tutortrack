import { unwrap, type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, Button, ErrorFallback, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";

import { api } from "../api";
import { ErrorList } from "./ErrorList";

type Settings = components["schemas"]["BookingSettings"];

const NUMBERS = [
  "min_notice_hours",
  "max_advance_days",
  "slot_interval_minutes",
  "buffer_minutes",
  "hold_minutes",
  "cancellation_window_hours",
] as const;

/** Online self-booking settings (FR-08-9, E08-T14). Services offered are those marked
 * "bookable online" in the catalogue. */
export function BookingSettingsPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<Settings | null>(null);
  const settings = useQuery({
    queryKey: ["booking", "settings"],
    queryFn: async () => unwrap(await api.GET("/api/v1/booking/settings")),
  });
  useEffect(() => {
    if (settings.data && !draft) setDraft(settings.data);
  }, [settings.data, draft]);
  const save = useMutation({
    mutationFn: async (body: Settings) =>
      unwrap(await api.PUT("/api/v1/booking/settings", { body })),
    onSuccess: (data) => queryClient.setQueryData(["booking", "settings"], data),
  });
  if (settings.isError) {
    return (
      <ErrorFallback
        title={t("errors.generic")}
        retryLabel={t("errors.retry")}
        onRetry={() => void settings.refetch()}
      />
    );
  }
  if (!draft) return <Spinner label={t("grid.loading")} />;
  return (
    <section className="max-w-3xl space-y-4">
      <h1 className="text-2xl font-semibold">{t("booking.title")}</h1>
      <p className="text-sm text-muted-foreground">{t("booking.intro")}</p>
      <form
        className="space-y-4"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          save.mutate(draft);
        }}
      >
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={draft.enabled ?? false}
            onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })}
          />
          {t("booking.enabled")}
        </label>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={draft.allow_new_clients ?? false}
            onChange={(e) => setDraft({ ...draft, allow_new_clients: e.target.checked })}
          />
          {t("booking.allowNew")}
        </label>
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={draft.approval_required ?? false}
            onChange={(e) => setDraft({ ...draft, approval_required: e.target.checked })}
          />
          {t("booking.approval")}
        </label>
        <SelectField
          label={t("booking.payment")}
          value={draft.payment ?? "none"}
          onChange={(e) =>
            setDraft({ ...draft, payment: e.target.value as NonNullable<Settings["payment"]> })
          }
          options={[
            { value: "none", label: t("booking.paymentNone") },
            { value: "at_booking", label: t("booking.paymentAtBooking") },
          ]}
        />
        <div className="grid gap-3 sm:grid-cols-3">
          {NUMBERS.map((key) => (
            <TextField
              key={key}
              label={t(`booking.fields.${key}`)}
              type="number"
              min={0}
              value={String(draft[key] ?? "")}
              onChange={(e) => setDraft({ ...draft, [key]: Number(e.target.value) })}
            />
          ))}
        </div>
        <Button type="submit" disabled={save.isPending}>
          {t("booking.save")}
        </Button>
        {save.isSuccess ? <Alert tone="success">{t("booking.saved")}</Alert> : null}
        <ErrorList error={save.error} />
      </form>
    </section>
  );
}
