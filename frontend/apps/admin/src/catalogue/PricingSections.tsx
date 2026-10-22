import { unwrap } from "@tutortrack/api-client";
import { formatDate, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  buttonClass,
  figureCell,
  FormPanel,
  NamePlate,
  PanelRow,
  PanelRows,
  RuledPanel,
  RuledTable,
  SelectField,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

import { api, useOrganisation, usePermission } from "../api";
import { useIsPhone } from "../billing/useIsPhone";
import { PAGE, formatRate } from "./format";
import { PanelEmpty, PanelLoading } from "../billing/moneyUi";
import { Faded, MutationError, QueryState, Table } from "./shared";

/* E06 Phase 2 settings: rooms (T10), pay tiers and tutor rates (T07), holiday calendars
 * and premiums (T08), discounts, promo codes and price lists (T09). */

function Form({
  title,
  submit,
  onSubmit,
  pending,
  error,
  children,
}: {
  title: string;
  submit: string;
  onSubmit: () => void;
  pending: boolean;
  error: unknown;
  children: ReactNode;
}) {
  return (
    <FormPanel
      title={title}
      submit={submit}
      pending={pending}
      onSubmit={onSubmit}
      error={error ? <MutationError error={error} /> : null}
      columns={3}
    >
      {children}
    </FormPanel>
  );
}

function useSave<T>(key: string, fn: () => Promise<T>, reset: () => void) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      reset();
      void queryClient.invalidateQueries({ queryKey: ["pricing", key] });
    },
  });
}

function money(amount: string, currency: string) {
  return amount.trim() ? { amount: amount.trim(), currency } : null;
}

const WEEKDAYS = [0, 1, 2, 3, 4, 5, 6];

/** The first letter in upper case ("booked less than…" opens a sentence). */
function capitalise(text: string): string {
  return text ? text.charAt(0).toLocaleUpperCase() + text.slice(1) : text;
}

/** A file picker whose button matches a small secondary button. */
const fileInput =
  "max-w-full text-sm text-muted-foreground file:mr-3 file:h-8 file:cursor-pointer file:rounded-md file:border file:border-border file:bg-surface file:px-3 file:text-sm file:font-medium file:text-foreground hover:file:bg-muted";

// --- rooms ----------------------------------------------------------------------------------------

export function RoomsSection() {
  const { t } = useTranslation();
  const isPhone = useIsPhone();
  const canManage = usePermission("catalogue.manage");
  const empty = { location: "", name: "", capacity: "", resources: "" };
  const [draft, setDraft] = useState(empty);
  const rooms = useQuery({
    queryKey: ["pricing", "rooms"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/catalogue/rooms", { params: { query: PAGE } })),
  });
  const locations = useQuery({
    queryKey: ["catalogue", "locations"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/catalogue/locations", { params: { query: PAGE } })),
  });
  const add = useSave(
    "rooms",
    async () =>
      unwrap(
        await api.POST("/api/v1/catalogue/rooms", {
          body: {
            location: draft.location,
            name: draft.name,
            capacity: draft.capacity ? Number(draft.capacity) : null,
            resources_input: draft.resources
              .split(",")
              .map((name) => name.trim())
              .filter(Boolean)
              .map((name) => ({ name, quantity: 1 })),
          },
        }),
      ),
    () => setDraft(empty),
  );
  const places = (locations.data?.results ?? []).filter((l) => l.type !== "online");
  return (
    <div className="space-y-6">
      <QueryState query={rooms}>
        <Table
          caption={t("pricing.rooms.title")}
          loading={rooms.isPending}
          count={rooms.data?.results.length}
          empty={t("designS6.catalogue.noRooms")}
          columns={[
            { header: t("catalogue.name") },
            ...(isPhone ? [] : [{ header: t("pricing.rooms.location") }]),
            { header: t("pricing.rooms.capacity"), end: true, width: "w-24" },
            ...(isPhone ? [] : [{ header: t("pricing.rooms.resources") }]),
          ]}
        >
          {(rooms.data?.results ?? []).map((room) => (
            <tr key={room.id}>
              <td className="font-medium">
                {room.name}
                {isPhone ? (
                  <span className="block text-xs font-normal text-muted-foreground">
                    {[room.location_name, room.resources.map((r) => r.name).join(", ")]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                ) : null}
              </td>
              {isPhone ? null : <td>{room.location_name}</td>}
              <td className={figureCell}>{room.capacity ?? <Faded>–</Faded>}</td>
              {isPhone ? null : <td>{room.resources.map((r) => r.name).join(", ")}</td>}
            </tr>
          ))}
        </Table>
      </QueryState>
      {canManage ? (
        <Form
          title={t("pricing.rooms.new")}
          submit={t("pricing.rooms.create")}
          onSubmit={() => add.mutate()}
          pending={add.isPending}
          error={add.error}
        >
          <SelectField
            label={t("pricing.rooms.location")}
            value={draft.location}
            onChange={(e) => setDraft({ ...draft, location: e.target.value })}
            options={[
              { value: "", label: t("pricing.choose") },
              ...places.map((l) => ({ value: l.id, label: l.name })),
            ]}
            required
          />
          <TextField
            label={t("catalogue.name")}
            value={draft.name}
            onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            required
          />
          <TextField
            label={t("pricing.rooms.capacity")}
            type="number"
            min={1}
            value={draft.capacity}
            onChange={(e) => setDraft({ ...draft, capacity: e.target.value })}
          />
          <TextField
            label={t("pricing.rooms.resources")}
            hint={t("pricing.rooms.resourcesHint")}
            value={draft.resources}
            onChange={(e) => setDraft({ ...draft, resources: e.target.value })}
          />
        </Form>
      ) : null}
    </div>
  );
}

// --- pay tiers ------------------------------------------------------------------------------------

export function PayTiersSection() {
  const { t, i18n } = useTranslation();
  const isPhone = useIsPhone();
  const locale = i18n.language;
  const canManage = usePermission("rates.manage");
  const queryClient = useQueryClient();
  const [tierName, setTierName] = useState("");
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [upload, setUpload] = useState<File | null>(null);
  const grid = useQuery({
    queryKey: ["pricing", "tier-rates"],
    queryFn: async () => unwrap(await api.GET("/api/v1/catalogue/tier-rates")),
  });
  const services = useQuery({
    queryKey: ["catalogue", "services", "active"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/catalogue/services", {
          params: { query: { ...PAGE, active: true } },
        }),
      ),
  });
  const addTier = useSave(
    "tier-rates",
    async () => unwrap(await api.POST("/api/v1/catalogue/pay-tiers", { body: { name: tierName } })),
    () => setTierName(""),
  );
  const save = useMutation({
    mutationFn: async () => {
      const cells = Object.entries(edits).map(([key, amount]) => {
        const [service = "", tier = ""] = key.split(":");
        const currency = services.data?.results.find((s) => s.id === service)?.currency ?? "GBP";
        return { service, tier, pay_rate: money(amount, currency) };
      });
      return unwrap(await api.POST("/api/v1/catalogue/tier-rates", { body: { cells } }));
    },
    onSuccess: (data) => {
      setEdits({});
      queryClient.setQueryData(["pricing", "tier-rates"], data);
    },
  });
  const importCsv = useMutation({
    mutationFn: async () => {
      const form = new FormData();
      form.append("file", upload as File);
      const response = await fetch("/api/v1/catalogue/tier-rates/csv", {
        method: "POST",
        body: form,
        credentials: "same-origin",
        headers: { "X-CSRFToken": document.cookie.match(/csrftoken=([^;]+)/)?.[1] ?? "" },
      });
      if (!response.ok) throw new Error(String(response.status));
      return (await response.json()) as { updated: number; row_errors: { row: number }[] };
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["pricing", "tier-rates"] }),
  });
  const tiers = grid.data?.tiers ?? [];
  const cell = (service: string, tier: string) =>
    grid.data?.cells.find((c) => c.service === service && c.tier === tier);
  const serviceRows = services.data?.results ?? [];
  return (
    <div className="space-y-6">
      <QueryState query={grid}>
        <RuledPanel
          flush
          title={t("pricing.tiers.grid")}
          description={t("pricing.tiers.intro")}
          footer={
            canManage && tiers.length ? (
              <>
                <a
                  className={buttonClass({ variant: "secondary", size: "sm" })}
                  href="/api/v1/catalogue/tier-rates/csv"
                  download
                >
                  {t("pricing.tiers.export")}
                </a>
                <label className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{t("pricing.tiers.importLabel")}</span>
                  <input
                    className={fileInput}
                    type="file"
                    accept=".csv,text/csv"
                    onChange={(e) => setUpload(e.target.files?.[0] ?? null)}
                  />
                </label>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => importCsv.mutate()}
                  disabled={!upload}
                  loading={importCsv.isPending}
                >
                  {t("pricing.tiers.import")}
                </Button>
                <Button
                  className="sm:ml-auto"
                  onClick={() => save.mutate()}
                  disabled={!Object.keys(edits).length}
                  loading={save.isPending}
                >
                  {t("pricing.tiers.save")}
                </Button>
              </>
            ) : null
          }
        >
          {!grid.isPending && !tiers.length ? (
            <PanelEmpty>{t("designS6.catalogue.noTiers")}</PanelEmpty>
          ) : (
            <>
              {isPhone && tiers.length > 1 ? (
                <p className="px-5 pt-3 text-xs text-muted-foreground">
                  {t("designS6.catalogue.scrollTiers")}
                </p>
              ) : null}
              <RuledTable
                caption={t("pricing.tiers.grid")}
                tableClassName="[&_td:first-child]:min-w-36"
                loading={grid.isPending || services.isPending}
                loadingLabel={t("grid.loading")}
                empty={
                  !services.isPending && !serviceRows.length
                    ? t("designS6.catalogue.noServices")
                    : undefined
                }
                columns={[
                  { header: t("catalogue.tabs.services") },
                  ...tiers.map((tier) => ({
                    key: tier.id,
                    header: tier.name,
                    end: true,
                    width: "w-32",
                  })),
                ]}
              >
                {serviceRows.map((service) => (
                  <tr key={service.id}>
                    <td className="font-medium">{service.name}</td>
                    {tiers.map((tier) => {
                      const key = `${service.id}:${tier.id}`;
                      const current = cell(service.id, tier.id)?.pay_rate;
                      return (
                        <td key={tier.id} className={canManage ? "py-1.5" : figureCell}>
                          {canManage ? (
                            <TextField
                              label={t("pricing.tiers.payFor", {
                                service: service.name,
                                tier: tier.name,
                              })}
                              hideLabel
                              size="sm"
                              className="ml-auto w-24 text-right tabular-nums"
                              inputMode="decimal"
                              value={edits[key] ?? (current ? String(Number(current.amount)) : "")}
                              onChange={(e) => setEdits({ ...edits, [key]: e.target.value })}
                            />
                          ) : current ? (
                            formatRate(current, locale)
                          ) : (
                            <Faded>–</Faded>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </RuledTable>
            </>
          )}
          {importCsv.data || save.error || importCsv.error ? (
            <div className="space-y-3 border-t border-rule px-5 py-4">
              {importCsv.data ? (
                <Alert tone={importCsv.data.row_errors.length ? "warning" : "success"}>
                  {importCsv.data.row_errors.length
                    ? t("pricing.tiers.importErrors", {
                        rows: importCsv.data.row_errors.map((e) => e.row).join(", "),
                      })
                    : t("pricing.tiers.imported", { count: importCsv.data.updated })}
                </Alert>
              ) : null}
              <MutationError error={save.error ?? importCsv.error} />
            </div>
          ) : null}
        </RuledPanel>
      </QueryState>
      {canManage ? (
        <Form
          title={t("pricing.tiers.new")}
          submit={t("pricing.tiers.create")}
          onSubmit={() => addTier.mutate()}
          pending={addTier.isPending}
          error={addTier.error}
        >
          <TextField
            label={t("catalogue.name")}
            value={tierName}
            onChange={(e) => setTierName(e.target.value)}
            required
          />
        </Form>
      ) : null}
    </div>
  );
}

// --- holidays and premiums ------------------------------------------------------------------------

export function PremiumsSection() {
  const { t, i18n } = useTranslation();
  const { data: org } = useOrganisation();
  const currency = org?.default_currency ?? "GBP";
  const canManage = usePermission("rates.manage");
  const empty = {
    name: "",
    weekdays: [] as number[],
    time_from: "",
    public_holidays: false,
    short_notice_hours: "",
    charge_percent: "",
    pay_percent: "",
    charge_fixed: "",
  };
  const [draft, setDraft] = useState(empty);
  const rules = useQuery({
    queryKey: ["pricing", "premiums"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/catalogue/premiums", { params: { query: PAGE } })),
  });
  const add = useSave(
    "premiums",
    async () =>
      unwrap(
        await api.POST("/api/v1/catalogue/premiums", {
          body: {
            name: draft.name,
            weekdays: draft.weekdays,
            time_from: draft.time_from || null,
            public_holidays: draft.public_holidays,
            short_notice_hours: draft.short_notice_hours ? Number(draft.short_notice_hours) : null,
            charge_percent: draft.charge_percent || null,
            pay_percent: draft.pay_percent || null,
            charge_fixed: money(draft.charge_fixed, currency),
          },
        }),
      ),
    () => setDraft(empty),
  );
  const dayName = (day: number) =>
    new Intl.DateTimeFormat(i18n.language, { weekday: "short" }).format(
      new Date(Date.UTC(2024, 0, 1 + day)),
    );
  return (
    <div className="space-y-6">
      <QueryState query={rules}>
        <RuledPanel flush title={t("pricing.premiums.title")}>
          <RuledTable
            caption={t("pricing.premiums.title")}
            loading={rules.isPending}
            loadingLabel={t("grid.loading")}
            empty={
              rules.data && !rules.data.results.length
                ? t("designS6.catalogue.noPremiums")
                : undefined
            }
            columns={[
              { header: t("catalogue.name") },
              { header: t("pricing.premiums.when"), width: "min-w-48" },
              { header: t("pricing.premiums.charge"), end: true, width: "w-28" },
              { header: t("pricing.premiums.pay"), end: true, width: "w-28" },
            ]}
          >
            {(rules.data?.results ?? []).map((rule) => (
              <tr key={rule.id}>
                <td className="font-medium">{rule.name}</td>
                <td>
                  {capitalise(
                    [
                      (rule.weekdays ?? []).map(dayName).join(" "),
                      rule.time_from
                        ? t("pricing.premiums.from", { time: rule.time_from.slice(0, 5) })
                        : "",
                      rule.public_holidays ? t("pricing.premiums.holidays") : "",
                      rule.short_notice_hours
                        ? t("pricing.premiums.notice", { hours: rule.short_notice_hours })
                        : "",
                    ]
                      .filter(Boolean)
                      .join(", ") || t("pricing.premiums.always"),
                  )}
                </td>
                <td className={figureCell}>
                  {[
                    rule.charge_percent ? `+${Number(rule.charge_percent)}%` : "",
                    rule.charge_fixed ? `+${formatRate(rule.charge_fixed, i18n.language)}` : "",
                  ]
                    .filter(Boolean)
                    .join(" ") || <Faded>–</Faded>}
                </td>
                <td className={figureCell}>
                  {rule.pay_percent ? `+${Number(rule.pay_percent)}%` : <Faded>–</Faded>}
                </td>
              </tr>
            ))}
          </RuledTable>
        </RuledPanel>
      </QueryState>
      {canManage ? (
        <Form
          title={t("pricing.premiums.new")}
          submit={t("pricing.premiums.create")}
          onSubmit={() => add.mutate()}
          pending={add.isPending}
          error={add.error}
        >
          <TextField
            label={t("catalogue.name")}
            value={draft.name}
            onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            required
          />
          <fieldset className="sm:col-span-2">
            <legend className="mb-2 text-sm font-medium">{t("pricing.premiums.days")}</legend>
            <div className="flex flex-wrap gap-x-4 gap-y-2">
              {WEEKDAYS.map((day) => (
                <label key={day} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    className="size-4"
                    checked={draft.weekdays.includes(day)}
                    onChange={(e) =>
                      setDraft({
                        ...draft,
                        weekdays: e.target.checked
                          ? [...draft.weekdays, day]
                          : draft.weekdays.filter((d) => d !== day),
                      })
                    }
                  />
                  {dayName(day)}
                </label>
              ))}
            </div>
          </fieldset>
          <TextField
            label={t("pricing.premiums.startsFrom")}
            type="time"
            value={draft.time_from}
            onChange={(e) => setDraft({ ...draft, time_from: e.target.value })}
          />
          <label className="flex items-center gap-2 text-sm sm:mt-7">
            <input
              type="checkbox"
              className="size-4"
              checked={draft.public_holidays}
              onChange={(e) => setDraft({ ...draft, public_holidays: e.target.checked })}
            />
            {t("pricing.premiums.onHolidays")}
          </label>
          <TextField
            label={t("pricing.premiums.shortNotice")}
            type="number"
            min={1}
            value={draft.short_notice_hours}
            onChange={(e) => setDraft({ ...draft, short_notice_hours: e.target.value })}
          />
          <TextField
            label={t("pricing.premiums.chargePercent")}
            inputMode="decimal"
            className="text-right tabular-nums"
            value={draft.charge_percent}
            onChange={(e) => setDraft({ ...draft, charge_percent: e.target.value })}
          />
          <TextField
            label={t("pricing.premiums.chargeFixed")}
            inputMode="decimal"
            className="text-right tabular-nums"
            value={draft.charge_fixed}
            onChange={(e) => setDraft({ ...draft, charge_fixed: e.target.value })}
          />
          <TextField
            label={t("pricing.premiums.payPercent")}
            inputMode="decimal"
            className="text-right tabular-nums"
            value={draft.pay_percent}
            onChange={(e) => setDraft({ ...draft, pay_percent: e.target.value })}
          />
        </Form>
      ) : null}
      <HolidaysSection />
    </div>
  );
}

function HolidaysSection() {
  const { t, i18n } = useTranslation();
  const canManage = usePermission("catalogue.manage");
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [year, setYear] = useState(String(new Date().getFullYear()));
  const calendars = useQuery({
    queryKey: ["pricing", "holidays"],
    queryFn: async () => unwrap(await api.GET("/api/v1/catalogue/holiday-calendars")),
  });
  const add = useSave(
    "holidays",
    async () =>
      unwrap(
        await api.POST("/api/v1/catalogue/holiday-calendars", {
          body: { name, country: "GB" },
        }),
      ),
    () => setName(""),
  );
  const importYear = useMutation({
    mutationFn: async (id: string) =>
      unwrap(
        await api.POST("/api/v1/catalogue/holiday-calendars/{id}/import", {
          params: { path: { id } },
          body: { year: Number(year) },
        }),
      ),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["pricing", "holidays"] }),
  });
  const list = calendars.data ?? [];
  return (
    <div className="space-y-6">
      <QueryState query={calendars}>
        <RuledPanel
          flush
          titleId="holidays-heading"
          title={t("pricing.holidays.title")}
          description={t("pricing.holidays.intro")}
        >
          {canManage && list.length ? (
            // The year the Add buttons import, read before the buttons it drives.
            <div className="flex items-center gap-3 border-b border-rule px-5 py-2.5">
              <label htmlFor="holiday-year" className="text-sm font-medium">
                {t("pricing.holidays.year")}
              </label>
              <input
                id="holiday-year"
                type="number"
                className="h-9 w-24 rounded-md border border-field bg-surface px-3 text-right text-sm tabular-nums"
                value={year}
                onChange={(e) => setYear(e.target.value)}
              />
            </div>
          ) : null}
          {calendars.isPending ? (
            <PanelLoading label={t("grid.loading")} />
          ) : !list.length ? (
            <PanelEmpty>{t("designS6.catalogue.noCalendars")}</PanelEmpty>
          ) : (
            <PanelRows>
              {list.map((calendar) => (
                <PanelRow key={calendar.id}>
                  <NamePlate
                    name={calendar.name}
                    context={
                      <span className="tabular-nums">
                        {[
                          t("designS6.catalogue.holidayCount", {
                            count: calendar.holidays.length,
                          }),
                          ...calendar.holidays
                            .slice(0, 12)
                            .map((h) => `${formatDate(h.date, i18n.language)} ${h.name}`),
                        ].join(" · ")}
                      </span>
                    }
                    aside={
                      canManage ? (
                        <Button
                          size="sm"
                          variant="secondary"
                          loading={importYear.isPending && importYear.variables === calendar.id}
                          onClick={() => importYear.mutate(calendar.id)}
                          aria-label={t("pricing.holidays.importNamed", {
                            name: calendar.name,
                            year,
                          })}
                        >
                          {t("pricing.holidays.import", { year })}
                        </Button>
                      ) : null
                    }
                  />
                </PanelRow>
              ))}
            </PanelRows>
          )}
          {importYear.error ? (
            <div className="border-t border-rule px-5 py-4">
              <MutationError error={importYear.error} />
            </div>
          ) : null}
        </RuledPanel>
      </QueryState>
      {canManage ? (
        <Form
          title={t("pricing.holidays.new")}
          submit={t("pricing.holidays.create")}
          onSubmit={() => add.mutate()}
          pending={add.isPending}
          error={add.error}
        >
          <TextField
            label={t("catalogue.name")}
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
        </Form>
      ) : null}
    </div>
  );
}

// --- discounts, promo codes and price lists -------------------------------------------------------

const KINDS = [
  "sibling",
  "volume",
  "multi_class",
  "first_lesson",
  "client",
  "scholarship",
  "promo",
] as const;

export function DiscountsSection() {
  const { t, i18n } = useTranslation();
  const isPhone = useIsPhone();
  const { data: org } = useOrganisation();
  const currency = org?.default_currency ?? "GBP";
  const canManage = usePermission("rates.manage");
  const empty = {
    name: "",
    kind: "sibling",
    percent: "",
    fixed_price: "",
    volume: "",
    classes: "",
    code: "",
  };
  const [draft, setDraft] = useState(empty);
  const discounts = useQuery({
    queryKey: ["pricing", "discounts"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/catalogue/discounts", { params: { query: PAGE } })),
  });
  const codes = useQuery({
    queryKey: ["pricing", "promo-codes"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/catalogue/promo-codes", { params: { query: PAGE } })),
  });
  const queryClient = useQueryClient();
  const add = useMutation({
    mutationFn: async () => {
      const rule = unwrap(
        await api.POST("/api/v1/catalogue/discounts", {
          body: {
            name: draft.name,
            kind: draft.kind as (typeof KINDS)[number],
            percent: draft.percent || null,
            fixed_price: money(draft.fixed_price, currency),
            volume_min_lessons: draft.volume ? Number(draft.volume) : null,
            min_classes: draft.classes ? Number(draft.classes) : null,
          },
        }),
      );
      if (draft.kind === "promo" && draft.code) {
        unwrap(
          await api.POST("/api/v1/catalogue/promo-codes", {
            body: { code: draft.code, discount: rule.id },
          }),
        );
      }
      return rule;
    },
    onSuccess: () => {
      setDraft(empty);
      void queryClient.invalidateQueries({ queryKey: ["pricing"] });
    },
  });
  return (
    <div className="space-y-6">
      <QueryState query={discounts}>
        <RuledPanel flush title={t("pricing.discounts.title")}>
          <RuledTable
            caption={t("pricing.discounts.title")}
            loading={discounts.isPending}
            loadingLabel={t("grid.loading")}
            empty={
              discounts.data && !discounts.data.results.length
                ? t("designS6.catalogue.noDiscounts")
                : undefined
            }
            columns={[
              { header: t("catalogue.name") },
              ...(isPhone ? [] : [{ header: t("pricing.discounts.kind") }]),
              { header: t("pricing.discounts.effect"), end: true, width: "w-32" },
            ]}
          >
            {(discounts.data?.results ?? []).map((rule) => (
              <tr key={rule.id}>
                <td className="font-medium">
                  {rule.name}
                  {isPhone ? (
                    <span className="block text-xs font-normal text-muted-foreground">
                      {t(`pricing.discounts.kinds.${rule.kind}`)}
                    </span>
                  ) : null}
                </td>
                {isPhone ? null : <td>{t(`pricing.discounts.kinds.${rule.kind}`)}</td>}
                <td className={figureCell}>
                  {[
                    rule.percent ? `\u2212${Number(rule.percent)}%` : "",
                    rule.fixed_price ? formatRate(rule.fixed_price, i18n.language) : "",
                  ]
                    .filter(Boolean)
                    .join(" ") || <Faded>–</Faded>}
                </td>
              </tr>
            ))}
          </RuledTable>
        </RuledPanel>
      </QueryState>
      <QueryState query={codes}>
        <RuledPanel flush title={t("pricing.discounts.codes")}>
          <RuledTable
            caption={t("pricing.discounts.codes")}
            loading={codes.isPending}
            loadingLabel={t("grid.loading")}
            empty={
              codes.data && !codes.data.results.length ? t("designS6.catalogue.noCodes") : undefined
            }
            columns={[
              { header: t("pricing.discounts.code") },
              { header: t("pricing.discounts.discount") },
              { header: t("pricing.discounts.uses"), end: true, width: "w-28" },
            ]}
          >
            {(codes.data?.results ?? []).map((code) => (
              <tr key={code.id}>
                <td className="font-medium tracking-wide">{code.code}</td>
                <td>{code.discount_name}</td>
                <td className={figureCell}>
                  {code.max_uses
                    ? t("designS6.catalogue.usesOf", { uses: code.uses, max: code.max_uses })
                    : code.uses}
                </td>
              </tr>
            ))}
          </RuledTable>
        </RuledPanel>
      </QueryState>
      {canManage ? (
        <Form
          title={t("pricing.discounts.new")}
          submit={t("pricing.discounts.create")}
          onSubmit={() => add.mutate()}
          pending={add.isPending}
          error={add.error}
        >
          <TextField
            label={t("catalogue.name")}
            value={draft.name}
            onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            required
          />
          <SelectField
            label={t("pricing.discounts.kind")}
            value={draft.kind}
            onChange={(e) => setDraft({ ...draft, kind: e.target.value })}
            options={KINDS.filter((k) => !["client", "scholarship"].includes(k)).map((k) => ({
              value: k,
              label: t(`pricing.discounts.kinds.${k}`),
            }))}
          />
          <TextField
            label={t("pricing.discounts.percent")}
            inputMode="decimal"
            className="text-right tabular-nums"
            value={draft.percent}
            onChange={(e) => setDraft({ ...draft, percent: e.target.value })}
          />
          {draft.kind === "first_lesson" ? (
            <TextField
              label={t("pricing.discounts.trialPrice")}
              inputMode="decimal"
              className="text-right tabular-nums"
              value={draft.fixed_price}
              onChange={(e) => setDraft({ ...draft, fixed_price: e.target.value })}
            />
          ) : null}
          {draft.kind === "volume" ? (
            <TextField
              label={t("pricing.discounts.volume")}
              type="number"
              min={1}
              value={draft.volume}
              onChange={(e) => setDraft({ ...draft, volume: e.target.value })}
            />
          ) : null}
          {draft.kind === "multi_class" ? (
            <TextField
              label={t("pricing.discounts.classes")}
              type="number"
              min={2}
              value={draft.classes}
              onChange={(e) => setDraft({ ...draft, classes: e.target.value })}
            />
          ) : null}
          {draft.kind === "promo" ? (
            <TextField
              label={t("pricing.discounts.code")}
              value={draft.code}
              onChange={(e) => setDraft({ ...draft, code: e.target.value })}
            />
          ) : null}
        </Form>
      ) : null}
    </div>
  );
}

export function PriceListsSection() {
  const { t, i18n } = useTranslation();
  const { data: org } = useOrganisation();
  const currency = org?.default_currency ?? "GBP";
  const locale = i18n.language;
  const canManage = usePermission("rates.manage");
  const empty = { name: "", service: "", rate: "" };
  const [draft, setDraft] = useState(empty);
  const lists = useQuery({
    queryKey: ["pricing", "price-lists"],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/catalogue/price-lists", { params: { query: PAGE } })),
  });
  const services = useQuery({
    queryKey: ["catalogue", "services", "active"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/catalogue/services", {
          params: { query: { ...PAGE, active: true } },
        }),
      ),
  });
  const add = useSave(
    "price-lists",
    async () =>
      unwrap(
        await api.POST("/api/v1/catalogue/price-lists", {
          body: {
            name: draft.name,
            currency,
            items_input: draft.service
              ? [{ service: draft.service, charge_rate: { amount: draft.rate, currency } }]
              : [],
          },
        }),
      ),
    () => setDraft(empty),
  );
  const serviceName = (id: string) => services.data?.results.find((s) => s.id === id)?.name ?? id;
  return (
    <div className="space-y-6">
      <QueryState query={lists}>
        <RuledPanel
          flush
          title={t("pricing.priceLists.title")}
          description={t("pricing.priceLists.intro")}
        >
          <RuledTable
            caption={t("pricing.priceLists.title")}
            loading={lists.isPending}
            loadingLabel={t("grid.loading")}
            empty={
              lists.data && !lists.data.results.length
                ? t("designS6.catalogue.noPriceLists")
                : undefined
            }
            columns={[
              { header: t("catalogue.name") },
              { header: t("pricing.priceLists.prices") },
              { header: t("pricing.priceLists.clients"), end: true, width: "w-24" },
            ]}
          >
            {(lists.data?.results ?? []).map((list) => (
              <tr key={list.id}>
                <td className="font-medium">{list.name}</td>
                <td className="tabular-nums">
                  {(list.items ?? [])
                    .map(
                      (item) =>
                        `${serviceName(item.service)} ${formatRate(item.charge_rate, locale)}`,
                    )
                    .join(", ")}
                </td>
                <td className={figureCell}>{list.clients.length}</td>
              </tr>
            ))}
          </RuledTable>
        </RuledPanel>
      </QueryState>
      {canManage ? (
        <Form
          title={t("pricing.priceLists.new")}
          submit={t("pricing.priceLists.create")}
          onSubmit={() => add.mutate()}
          pending={add.isPending}
          error={add.error}
        >
          <TextField
            label={t("catalogue.name")}
            value={draft.name}
            onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            required
          />
          <SelectField
            label={t("pricing.priceLists.service")}
            value={draft.service}
            onChange={(e) => setDraft({ ...draft, service: e.target.value })}
            options={[
              { value: "", label: t("pricing.choose") },
              ...(services.data?.results ?? []).map((s) => ({ value: s.id, label: s.name })),
            ]}
          />
          <TextField
            label={t("pricing.priceLists.rate")}
            inputMode="decimal"
            className="text-right tabular-nums"
            value={draft.rate}
            onChange={(e) => setDraft({ ...draft, rate: e.target.value })}
          />
        </Form>
      ) : null}
    </div>
  );
}
