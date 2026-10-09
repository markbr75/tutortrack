import { unwrap, type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, TextField } from "@tutortrack/ui";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api, useOrganisation } from "../api";
import { PAGE, formatRate } from "./format";
import { MutationError } from "./shared";

type Quote = components["schemas"]["RateQuote"];

/** Dry-run the rate engine (FR-06-4): pick a service, students and a tutor and see the
 * charge and pay lines with the explanation trace. */
export function PriceCheck() {
  const { t, i18n } = useTranslation();
  const { data: org } = useOrganisation();
  const currency = org?.default_currency ?? "GBP";
  const [service, setService] = useState("");
  const [minutes, setMinutes] = useState("60");
  const [students, setStudents] = useState<string[]>([]);
  const [tutor, setTutor] = useState("");
  const [jobRate, setJobRate] = useState("");
  const services = useQuery({
    queryKey: ["catalogue", "services"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/catalogue/services", { params: { query: PAGE } })),
  });
  const studentList = useQuery({
    queryKey: ["students", "price-check"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/students", {
          params: { query: { status: ["active", "trial"], page_size: 100 } },
        }),
      ),
  });
  const tutorList = useQuery({
    queryKey: ["tutors", "price-check"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/tutors", {
          params: { query: { status: ["active"], page_size: 100 } },
        }),
      ),
  });
  const names = new Map<string, string>([
    ...(studentList.data?.results ?? []).map((s) => [s.id, s.full_name] as [string, string]),
    ...(tutorList.data?.results ?? []).map((s) => [s.id, s.full_name] as [string, string]),
  ]);
  const quote = useMutation({
    mutationFn: async (): Promise<Quote> =>
      unwrap(
        await api.POST("/api/v1/rates/quote", {
          body: {
            service,
            duration_minutes: Number(minutes),
            students: students.map((id) => ({ student: id })),
            tutors: tutor ? [{ tutor }] : [],
            job_charge_rate: jobRate ? { amount: jobRate, currency } : null,
          },
        }),
      ),
  });
  const result = quote.data;
  return (
    <div className="space-y-6">
      <form
        className="space-y-4 rounded-lg border border-border p-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (service && students.length) quote.mutate();
        }}
      >
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <SelectField
            label={t("catalogue.price.service")}
            required
            value={service}
            onChange={(e) => setService(e.target.value)}
            options={[
              { value: "", label: t("catalogue.price.choose") },
              ...(services.data?.results ?? []).map((s) => ({ value: s.id, label: s.name })),
            ]}
          />
          <TextField
            label={t("catalogue.services.duration")}
            type="number"
            min={5}
            max={600}
            value={minutes}
            onChange={(e) => setMinutes(e.target.value)}
          />
          <SelectField
            label={t("catalogue.price.tutor")}
            value={tutor}
            onChange={(e) => setTutor(e.target.value)}
            options={[
              { value: "", label: t("catalogue.price.noTutor") },
              ...(tutorList.data?.results ?? []).map((s) => ({ value: s.id, label: s.full_name })),
            ]}
          />
          <TextField
            label={t("catalogue.price.jobRate", { currency })}
            hint={t("catalogue.price.jobRateHint")}
            inputMode="decimal"
            value={jobRate}
            onChange={(e) => setJobRate(e.target.value)}
          />
        </div>
        <fieldset>
          <legend className="mb-2 text-sm font-medium">{t("catalogue.price.students")}</legend>
          <div className="grid max-h-48 gap-1 overflow-y-auto sm:grid-cols-3">
            {(studentList.data?.results ?? []).map((s) => (
              <label key={s.id} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  className="size-4"
                  checked={students.includes(s.id)}
                  onChange={(e) =>
                    setStudents((list) =>
                      e.target.checked ? [...list, s.id] : list.filter((id) => id !== s.id),
                    )
                  }
                />
                {s.full_name}
              </label>
            ))}
          </div>
        </fieldset>
        <Button type="submit" disabled={quote.isPending || !service || students.length === 0}>
          {t("catalogue.price.check")}
        </Button>
        <MutationError error={quote.error} />
      </form>

      {result ? (
        <section aria-live="polite" className="space-y-4">
          {result.charges ? (
            <div>
              <h2 className="font-semibold">
                {t("catalogue.price.charges")}: {formatRate(result.total_charge, i18n.language)}
              </h2>
              <ul className="mt-2 space-y-2">
                {result.charges.map((line) => (
                  <li key={line.student_id} className="rounded-md border border-border p-2 text-sm">
                    <p className="font-medium">
                      {names.get(line.student_id) ?? line.student_id}:{" "}
                      {formatRate(line.amount, i18n.language)}
                    </p>
                    <p className="text-muted-foreground">{line.trace.join(" · ")}</p>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {result.pay ? (
            <div>
              <h2 className="font-semibold">
                {t("catalogue.price.pay")}: {formatRate(result.total_pay, i18n.language)}
              </h2>
              <ul className="mt-2 space-y-2">
                {result.pay.map((line) => (
                  <li key={line.tutor_id} className="rounded-md border border-border p-2 text-sm">
                    <p className="font-medium">
                      {names.get(line.tutor_id) ?? line.tutor_id}:{" "}
                      {formatRate(line.amount, i18n.language)}
                    </p>
                    <p className="text-muted-foreground">{line.trace.join(" · ")}</p>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {!result.charges && !result.pay ? <Alert>{t("catalogue.price.noAccess")}</Alert> : null}
        </section>
      ) : null}
    </div>
  );
}
