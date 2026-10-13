import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent, type ReactNode } from "react";

import { api, useOrganisation, usePermission } from "../api";
import { PAGE, formatRate } from "./format";
import { Cell, MutationError, QueryState, Table } from "./shared";

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
    <form
      className="space-y-3 rounded-lg border border-border p-4"
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        onSubmit();
      }}
    >
      <h2 className="font-semibold">{title}</h2>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{children}</div>
      <Button type="submit" disabled={pending}>
        {submit}
      </Button>
      <MutationError error={error} />
    </form>
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

// --- rooms ----------------------------------------------------------------------------------------

export function RoomsSection() {
  const { t } = useTranslation();
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
          headers={[
            t("catalogue.name"),
            t("pricing.rooms.location"),
            t("pricing.rooms.capacity"),
            t("pricing.rooms.resources"),
          ]}
        >
          {(rooms.data?.results ?? []).map((room) => (
            <tr key={room.id}>
              <Cell>{room.name}</Cell>
              <Cell>{room.location_name}</Cell>
              <Cell>{room.capacity ?? "—"}</Cell>
              <Cell>{room.resources.map((r) => r.name).join(", ")}</Cell>
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
  return (
    <div className="space-y-6">
      <p className="text-sm text-muted-foreground">{t("pricing.tiers.intro")}</p>
      <QueryState query={grid}>
        <Table
          caption={t("pricing.tiers.grid")}
          headers={[t("catalogue.tabs.services"), ...tiers.map((tier) => tier.name)]}
        >
          {(services.data?.results ?? []).map((service) => (
            <tr key={service.id}>
              <Cell>{service.name}</Cell>
              {tiers.map((tier) => {
                const key = `${service.id}:${tier.id}`;
                const current = cell(service.id, tier.id)?.pay_rate;
                return (
                  <Cell key={tier.id}>
                    {canManage ? (
                      <TextField
                        label={t("pricing.tiers.payFor", {
                          service: service.name,
                          tier: tier.name,
                        })}
                        className="w-24"
                        inputMode="decimal"
                        value={edits[key] ?? (current ? String(Number(current.amount)) : "")}
                        onChange={(e) => setEdits({ ...edits, [key]: e.target.value })}
                      />
                    ) : (
                      formatRate(current, locale)
                    )}
                  </Cell>
                );
              })}
            </tr>
          ))}
        </Table>
      </QueryState>
      {canManage ? (
        <div className="flex flex-wrap items-end gap-3">
          <Button
            onClick={() => save.mutate()}
            disabled={!Object.keys(edits).length || save.isPending}
          >
            {t("pricing.tiers.save")}
          </Button>
          <a className="text-sm underline" href="/api/v1/catalogue/tier-rates/csv" download>
            {t("pricing.tiers.export")}
          </a>
          <label className="text-sm">
            {t("pricing.tiers.importLabel")}
            <input
              className="ml-2"
              type="file"
              accept=".csv,text/csv"
              onChange={(e) => setUpload(e.target.files?.[0] ?? null)}
            />
          </label>
          <Button variant="secondary" onClick={() => importCsv.mutate()} disabled={!upload}>
            {t("pricing.tiers.import")}
          </Button>
        </div>
      ) : null}
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
        <Table
          caption={t("pricing.premiums.title")}
          headers={[
            t("catalogue.name"),
            t("pricing.premiums.when"),
            t("pricing.premiums.charge"),
            t("pricing.premiums.pay"),
          ]}
        >
          {(rules.data?.results ?? []).map((rule) => (
            <tr key={rule.id}>
              <Cell>{rule.name}</Cell>
              <Cell>
                {[
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
                  .join(", ") || t("pricing.premiums.always")}
              </Cell>
              <Cell>{rule.charge_percent ? `+${Number(rule.charge_percent)}%` : ""}</Cell>
              <Cell>{rule.pay_percent ? `+${Number(rule.pay_percent)}%` : ""}</Cell>
            </tr>
          ))}
        </Table>
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
            <legend className="text-sm font-medium">{t("pricing.premiums.days")}</legend>
            <div className="flex flex-wrap gap-3">
              {WEEKDAYS.map((day) => (
                <label key={day} className="flex items-center gap-1 text-sm">
                  <input
                    type="checkbox"
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
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
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
            value={draft.charge_percent}
            onChange={(e) => setDraft({ ...draft, charge_percent: e.target.value })}
          />
          <TextField
            label={t("pricing.premiums.chargeFixed")}
            inputMode="decimal"
            value={draft.charge_fixed}
            onChange={(e) => setDraft({ ...draft, charge_fixed: e.target.value })}
          />
          <TextField
            label={t("pricing.premiums.payPercent")}
            inputMode="decimal"
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
  const { t } = useTranslation();
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
  return (
    <section className="space-y-3" aria-labelledby="holidays-heading">
      <h2 id="holidays-heading" className="text-lg font-semibold">
        {t("pricing.holidays.title")}
      </h2>
      <p className="text-sm text-muted-foreground">{t("pricing.holidays.intro")}</p>
      <QueryState query={calendars}>
        <ul className="space-y-3">
          {(calendars.data ?? []).map((calendar) => (
            <li key={calendar.id} className="rounded-lg border border-border p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-medium">
                  {calendar.name} ({calendar.holidays.length})
                </span>
                {canManage ? (
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => importYear.mutate(calendar.id)}
                    aria-label={t("pricing.holidays.importNamed", { name: calendar.name, year })}
                  >
                    {t("pricing.holidays.import", { year })}
                  </Button>
                ) : null}
              </div>
              <p className="mt-1 text-sm text-muted-foreground">
                {calendar.holidays
                  .slice(0, 12)
                  .map((h) => `${h.date} ${h.name}`)
                  .join(" · ")}
              </p>
            </li>
          ))}
        </ul>
      </QueryState>
      {canManage ? (
        <Form
          title={t("pricing.holidays.new")}
          submit={t("pricing.holidays.create")}
          onSubmit={() => add.mutate()}
          pending={add.isPending}
          error={add.error ?? importYear.error}
        >
          <TextField
            label={t("catalogue.name")}
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
          <TextField
            label={t("pricing.holidays.year")}
            type="number"
            value={year}
            onChange={(e) => setYear(e.target.value)}
          />
        </Form>
      ) : null}
    </section>
  );
}

// --- discounts, promo codes and price lists -------------------------------------------------------

const KINDS = ["sibling", "volume", "first_lesson", "client", "scholarship", "promo"] as const;

export function DiscountsSection() {
  const { t, i18n } = useTranslation();
  const { data: org } = useOrganisation();
  const currency = org?.default_currency ?? "GBP";
  const canManage = usePermission("rates.manage");
  const empty = { name: "", kind: "sibling", percent: "", fixed_price: "", volume: "", code: "" };
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
        <Table
          caption={t("pricing.discounts.title")}
          headers={[
            t("catalogue.name"),
            t("pricing.discounts.kind"),
            t("pricing.discounts.effect"),
          ]}
        >
          {(discounts.data?.results ?? []).map((rule) => (
            <tr key={rule.id}>
              <Cell>{rule.name}</Cell>
              <Cell>{t(`pricing.discounts.kinds.${rule.kind}`)}</Cell>
              <Cell>
                {rule.percent ? `-${Number(rule.percent)}%` : ""}
                {rule.fixed_price ? ` ${formatRate(rule.fixed_price, i18n.language)}` : ""}
              </Cell>
            </tr>
          ))}
        </Table>
      </QueryState>
      <QueryState query={codes}>
        <Table
          caption={t("pricing.discounts.codes")}
          headers={[
            t("pricing.discounts.code"),
            t("pricing.discounts.discount"),
            t("pricing.discounts.uses"),
          ]}
        >
          {(codes.data?.results ?? []).map((code) => (
            <tr key={code.id}>
              <Cell>
                <code>{code.code}</code>
              </Cell>
              <Cell>{code.discount_name}</Cell>
              <Cell>
                {code.uses}
                {code.max_uses ? ` / ${code.max_uses}` : ""}
              </Cell>
            </tr>
          ))}
        </Table>
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
            value={draft.percent}
            onChange={(e) => setDraft({ ...draft, percent: e.target.value })}
          />
          {draft.kind === "first_lesson" ? (
            <TextField
              label={t("pricing.discounts.trialPrice")}
              inputMode="decimal"
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
      <p className="text-sm text-muted-foreground">{t("pricing.priceLists.intro")}</p>
      <QueryState query={lists}>
        <Table
          caption={t("pricing.priceLists.title")}
          headers={[
            t("catalogue.name"),
            t("pricing.priceLists.prices"),
            t("pricing.priceLists.clients"),
          ]}
        >
          {(lists.data?.results ?? []).map((list) => (
            <tr key={list.id}>
              <Cell>{list.name}</Cell>
              <Cell>
                {(list.items ?? [])
                  .map(
                    (item) =>
                      `${serviceName(item.service)} ${formatRate(item.charge_rate, locale)}`,
                  )
                  .join(", ")}
              </Cell>
              <Cell>{list.clients.length}</Cell>
            </tr>
          ))}
        </Table>
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
            value={draft.rate}
            onChange={(e) => setDraft({ ...draft, rate: e.target.value })}
          />
        </Form>
      ) : null}
    </div>
  );
}
