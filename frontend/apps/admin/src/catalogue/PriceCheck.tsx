import { unwrap, type components } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  figureCell,
  FormPanel,
  RuledPanel,
  RuledTable,
  SelectField,
  TextField,
} from "@tutortrack/ui";
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
            online: false,
          },
        }),
      ),
  });
  const result = quote.data;
  const studentRows = studentList.data?.results ?? [];
  return (
    <div className="space-y-6">
      <FormPanel
        title={t("designS6.catalogue.priceCheck")}
        description={t("designS6.catalogue.priceCheckHelp")}
        submit={t("catalogue.price.check")}
        pending={quote.isPending}
        disabled={!service || students.length === 0}
        onSubmit={() => {
          if (service && students.length) quote.mutate();
        }}
        error={quote.error ? <MutationError error={quote.error} /> : null}
        columns={4}
      >
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
          className="tabular-nums"
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
          className="text-right tabular-nums"
          value={jobRate}
          onChange={(e) => setJobRate(e.target.value)}
        />
        <fieldset className="sm:col-span-full">
          <legend className="mb-2 text-sm font-medium">
            {t("catalogue.price.students")}
            {students.length ? (
              <span className="ml-2 font-normal text-muted-foreground tabular-nums">
                {t("designS6.catalogue.chosen", { count: students.length })}
              </span>
            ) : null}
          </legend>
          <div className="relative grid max-h-48 gap-x-4 gap-y-1.5 overflow-y-auto rounded-md border border-border px-3 py-2.5 sm:grid-cols-2 lg:grid-cols-3">
            {studentRows.map((s) => (
              <label key={s.id} className="flex min-w-0 items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  className="size-4 shrink-0"
                  checked={students.includes(s.id)}
                  onChange={(e) =>
                    setStudents((list) =>
                      e.target.checked ? [...list, s.id] : list.filter((id) => id !== s.id),
                    )
                  }
                />
                <span className="truncate">{s.full_name}</span>
              </label>
            ))}
          </div>
        </fieldset>
      </FormPanel>

      {result ? (
        <section aria-live="polite" className="grid items-start gap-6 lg:grid-cols-2">
          {result.charges ? (
            <QuoteLines
              title={t("catalogue.price.charges")}
              total={formatRate(result.total_charge, i18n.language)}
              who={t("learning.student")}
              lines={result.charges.map((line) => ({
                key: line.student_id,
                name: names.get(line.student_id) ?? line.student_id,
                trace: line.trace.join(" · "),
                amount: formatRate(line.amount, i18n.language),
              }))}
            />
          ) : null}
          {result.pay ? (
            <QuoteLines
              title={t("catalogue.price.pay")}
              total={formatRate(result.total_pay, i18n.language)}
              who={t("catalogue.price.tutor")}
              lines={result.pay.map((line) => ({
                key: line.tutor_id,
                name: names.get(line.tutor_id) ?? line.tutor_id,
                trace: line.trace.join(" · "),
                amount: formatRate(line.amount, i18n.language),
              }))}
            />
          ) : null}
          {!result.charges && !result.pay ? <Alert>{t("catalogue.price.noAccess")}</Alert> : null}
        </section>
      ) : null}
    </div>
  );
}

/** One side of a quote: a line per person with the rate engine's trace, and the total under
 * the amounts. The heading carries the total for screen readers too. */
function QuoteLines({
  title,
  total,
  who,
  lines,
}: {
  title: string;
  total: string;
  who: string;
  lines: { key: string; name: string; trace: string; amount: string }[];
}) {
  const { t } = useTranslation();
  return (
    <RuledPanel
      flush
      title={
        <>
          {title}
          <span className="sr-only">: {total}</span>
        </>
      }
    >
      <RuledTable
        caption={title}
        columns={[{ header: who }, { header: t("billing.amount"), end: true, width: "w-32" }]}
        footer={
          <tr>
            <th scope="row" className="py-2.5 text-right font-semibold">
              {t("billing.total")}
            </th>
            <td className={`${figureCell} font-semibold`}>{total}</td>
          </tr>
        }
      >
        {lines.map((line) => (
          <tr key={line.key}>
            <td>
              <span className="font-medium">{line.name}</span>
              <span className="block text-xs text-muted-foreground">{line.trace}</span>
            </td>
            <td className={figureCell}>{line.amount}</td>
          </tr>
        ))}
      </RuledTable>
    </RuledPanel>
  );
}
