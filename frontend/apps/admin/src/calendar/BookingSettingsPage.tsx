import { unwrap, type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import {
  Button,
  CheckboxField,
  ErrorFallback,
  PageHeader,
  RuledPanel,
  SelectField,
  Spinner,
  UnitField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";

import { api } from "../api";
import { SavedNote } from "../components/SavedNote";
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
    <div className="max-w-3xl">
      <PageHeader title={t("booking.title")} description={t("booking.intro")} />
      <form
        aria-labelledby="booking-settings"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          save.mutate(draft);
        }}
      >
        <RuledPanel
          flush
          titleId="booking-settings"
          title={t("designS9b.booking.panel")}
          footer={
            <>
              <Button type="submit" loading={save.isPending}>
                {t("booking.save")}
              </Button>
              <SavedNote show={save.isSuccess} text={t("booking.saved")} />
            </>
          }
        >
          <div className="space-y-2 px-5 py-4">
            <CheckboxField
              label={t("booking.enabled")}
              checked={draft.enabled ?? false}
              onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })}
            />
            <CheckboxField
              label={t("booking.allowNew")}
              checked={draft.allow_new_clients ?? false}
              onChange={(e) => setDraft({ ...draft, allow_new_clients: e.target.checked })}
            />
            <CheckboxField
              label={t("booking.approval")}
              checked={draft.approval_required ?? false}
              onChange={(e) => setDraft({ ...draft, approval_required: e.target.checked })}
            />
          </div>
          <div className="border-t border-rule px-5 py-4">
            <SelectField
              className="sm:max-w-sm"
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
          </div>
          <div className="grid gap-x-4 gap-y-3 border-t border-rule px-5 py-4 sm:grid-cols-2 lg:grid-cols-3">
            {NUMBERS.map((key) => (
              <UnitField
                key={key}
                label={t(`booking.fields.${key}`)}
                min={0}
                value={String(draft[key] ?? "")}
                onChange={(e) => setDraft({ ...draft, [key]: Number(e.target.value) })}
              />
            ))}
          </div>
          {save.error ? (
            <div className="px-5 pb-4">
              <ErrorList error={save.error} />
            </div>
          ) : null}
        </RuledPanel>
      </form>
    </div>
  );
}
