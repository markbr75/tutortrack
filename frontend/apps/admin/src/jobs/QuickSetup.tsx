import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Button, SelectField, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";
import { useState } from "react";

import { api, fieldErrors, useOrganisation, usePermission } from "../api";
import { WEEKDAYS } from "./statuses";

/** "Set up lessons" for a student (FR-07-2 quick job): service, tutor, rate and a weekly
 * time in one step. */
export function QuickSetup({ studentId }: { studentId: string }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const canAssign = usePermission("jobs.job.manage_tutors");
  const canCharge = usePermission("billing.rates.view_charge");
  const { data: org } = useOrganisation();
  const currency = org?.default_currency ?? "GBP";
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    service: "",
    tutor: "",
    rate: "",
    weekday: "0",
    time: "16:00",
    start: "",
  });
  const services = useQuery({
    queryKey: ["catalogue", "services", "active"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/catalogue/services", {
          params: { query: { active: true, page_size: 200 } },
        }),
      ),
    enabled: open,
  });
  const tutors = useQuery({
    queryKey: ["tutors", "active"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/tutors", {
          params: { query: { status: ["active"], page_size: 200 } },
        }),
      ),
    enabled: open && canAssign,
  });
  const save = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/jobs/quick-setup", {
          body: {
            student: studentId,
            service: form.service,
            tutor: form.tutor || null,
            charge_rate: form.rate ? { amount: form.rate, currency } : null,
            schedule: form.time ? [{ weekday: Number(form.weekday), time: form.time }] : [],
            ...(form.start ? { start_date: form.start } : {}),
          },
        }),
      ),
    onSuccess: (job) => {
      void queryClient.invalidateQueries({ queryKey: ["jobs"] });
      void navigate({ to: "/jobs/$jobId", params: { jobId: job.id } });
    },
  });
  const set = (patch: Partial<typeof form>) => setForm((f) => ({ ...f, ...patch }));
  const errors = fieldErrors(save.error);
  if (!open) {
    return (
      <Button variant="secondary" onClick={() => setOpen(true)}>
        {t("jobs.quick.open")}
      </Button>
    );
  }
  return (
    <form
      className="space-y-3 rounded-lg border border-border p-4"
      aria-label={t("jobs.quick.open")}
      onSubmit={(e) => {
        e.preventDefault();
        if (form.service) save.mutate();
      }}
    >
      <h2 className="font-semibold">{t("jobs.quick.open")}</h2>
      <div className="grid gap-3 sm:grid-cols-2">
        <SelectField
          label={t("jobs.service")}
          required
          value={form.service}
          error={errors.service}
          onChange={(e) => set({ service: e.target.value })}
          options={[
            { value: "", label: t("catalogue.price.choose") },
            ...(services.data?.results ?? []).map((s) => ({ value: s.id, label: s.name })),
          ]}
        />
        {canAssign ? (
          <SelectField
            label={t("jobs.tutor")}
            value={form.tutor}
            onChange={(e) => set({ tutor: e.target.value })}
            options={[
              { value: "", label: t("jobs.quick.findLater") },
              ...(tutors.data?.results ?? []).map((p) => ({ value: p.id, label: p.full_name })),
            ]}
          />
        ) : null}
        {canCharge ? (
          <TextField
            label={t("jobs.quick.rate", { currency })}
            hint={t("jobs.quick.rateHint")}
            inputMode="decimal"
            value={form.rate}
            onChange={(e) => set({ rate: e.target.value })}
          />
        ) : null}
        <SelectField
          label={t("jobs.quick.day")}
          value={form.weekday}
          onChange={(e) => set({ weekday: e.target.value })}
          options={WEEKDAYS.map((d) => ({ value: String(d), label: t(`jobs.weekday.${d}`) }))}
        />
        <TextField
          label={t("jobs.quick.time")}
          type="time"
          value={form.time}
          onChange={(e) => set({ time: e.target.value })}
        />
        <TextField
          label={t("jobs.starts")}
          type="date"
          value={form.start}
          onChange={(e) => set({ start: e.target.value })}
        />
      </div>
      {save.isError && !errors.service ? (
        <p role="alert" className="text-sm text-danger">
          {Object.values(errors).join(" ") || t("errors.generic")}
        </p>
      ) : null}
      <div className="flex gap-2">
        <Button type="submit" disabled={!form.service || save.isPending}>
          {t("jobs.quick.save")}
        </Button>
        <Button type="button" variant="secondary" onClick={() => setOpen(false)}>
          {t("catalogue.cancel")}
        </Button>
      </div>
    </form>
  );
}
