import { unwrap, type components } from "@tutortrack/api-client";
import { formatDate, formatMoney, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  Panel,
  PanelRow,
  PanelRows,
  SelectField,
  Spinner,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";
import { useState } from "react";

import { api, fieldErrors, usePermission } from "../api";
import { PublicLayout } from "../layout/PublicLayout";
import { TutorCard } from "../matching/SharePages";

type Proposal = components["schemas"]["Proposal"];
type Line = { service: string; description: string; quantity: string; unit_price: string };

const EMPTY_LINE: Line = { service: "", description: "", quantity: "1", unit_price: "" };

function TextArea({
  id,
  label,
  value,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <textarea
        id={id}
        className="min-h-20 rounded-md border border-field bg-surface px-3 py-2 text-sm"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

function ProposalEditor({
  enquiryId,
  proposal,
  onDone,
}: {
  enquiryId: string;
  proposal: Proposal | null;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const [title, setTitle] = useState(proposal?.title ?? "");
  const [introduction, setIntroduction] = useState(proposal?.introduction ?? "");
  const [schedule, setSchedule] = useState(proposal?.schedule ?? "");
  const [lines, setLines] = useState<Line[]>(
    proposal?.lines.length
      ? proposal.lines.map((l) => ({
          service: l.service ?? "",
          description: l.description ?? "",
          quantity: l.quantity,
          unit_price: l.unit_price,
        }))
      : [EMPTY_LINE],
  );
  const [tutors, setTutors] = useState<string[]>(proposal?.tutors ?? []);
  const [deposit, setDeposit] = useState(proposal?.deposit?.amount ?? "");
  const [validDays, setValidDays] = useState(String(proposal?.valid_days ?? 14));
  const services = useQuery({
    queryKey: ["catalogue", "services", "proposal"],
    queryFn: async () => {
      const rows = unwrap(await api.GET("/api/v1/catalogue/services"));
      return Array.isArray(rows) ? rows : rows.results;
    },
  });
  const tutorList = useQuery({
    queryKey: ["tutors", "active", "proposal"],
    queryFn: async () =>
      unwrap(
        await api.GET("/api/v1/tutors", {
          params: { query: { status: ["active"], page_size: 200 } },
        }),
      ),
  });
  const save = useMutation({
    mutationFn: async () => {
      const body = {
        enquiry: enquiryId,
        title,
        introduction,
        schedule,
        lines: lines
          .filter((l) => l.unit_price !== "")
          .map((l) => ({ ...l, service: l.service || null })),
        tutors,
        currency: "",
        deposit: deposit === "" ? null : deposit,
        valid_days: Number(validDays) || null,
      };
      return proposal
        ? unwrap(
            await api.PATCH("/api/v1/proposals/{id}", {
              params: { path: { id: proposal.id } },
              body,
            }),
          )
        : unwrap(await api.POST("/api/v1/proposals", { body }));
    },
    onSuccess: onDone,
  });
  const errors = fieldErrors(save.error);
  const setLine = (index: number, patch: Partial<Line>) =>
    setLines(lines.map((l, i) => (i === index ? { ...l, ...patch } : l)));
  return (
    <form
      className="space-y-4 border-t border-border px-5 py-4"
      aria-label={t("proposals.editor")}
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <TextField
        label={t("proposals.titleField")}
        value={title}
        onChange={(e) => setTitle(e.target.value)}
      />
      <TextArea
        id="proposal-intro"
        label={t("proposals.introduction")}
        value={introduction}
        onChange={setIntroduction}
      />
      <TextArea
        id="proposal-schedule"
        label={t("proposals.schedule")}
        value={schedule}
        onChange={setSchedule}
      />
      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">{t("proposals.lines")}</legend>
        {lines.map((line, index) => (
          <div
            key={index}
            className="flex flex-wrap items-end gap-2"
            role="group"
            aria-label={t("proposals.lineN", { n: index + 1 })}
          >
            <SelectField
              label={t("proposals.service")}
              value={line.service}
              onChange={(e) => setLine(index, { service: e.target.value })}
              options={[
                { value: "", label: t("proposals.noService") },
                ...(services.data ?? []).map((s) => ({ value: s.id, label: s.name })),
              ]}
            />
            <TextField
              label={t("proposals.description")}
              value={line.description}
              onChange={(e) => setLine(index, { description: e.target.value })}
            />
            <TextField
              label={t("proposals.quantity")}
              inputMode="decimal"
              value={line.quantity}
              onChange={(e) => setLine(index, { quantity: e.target.value })}
            />
            <TextField
              label={t("proposals.unitPrice")}
              inputMode="decimal"
              value={line.unit_price}
              onChange={(e) => setLine(index, { unit_price: e.target.value })}
            />
            <Button
              type="button"
              variant="ghost"
              onClick={() => setLines(lines.filter((_l, i) => i !== index))}
              aria-label={t("proposals.removeLine", { n: index + 1 })}
            >
              {t("proposals.remove")}
            </Button>
          </div>
        ))}
        <Button
          type="button"
          size="sm"
          variant="secondary"
          onClick={() => setLines([...lines, EMPTY_LINE])}
        >
          {t("proposals.addLine")}
        </Button>
        {errors.lines ? <p className="text-xs text-danger">{errors.lines}</p> : null}
      </fieldset>
      <fieldset>
        <legend className="text-sm font-medium">{t("proposals.tutors")}</legend>
        <div className="relative mt-1 max-h-40 space-y-1 overflow-y-auto rounded-md border border-border px-3 py-2">
          {(tutorList.data?.results ?? []).map((tutor) => (
            <label key={tutor.id} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                className="size-4"
                checked={tutors.includes(tutor.id)}
                onChange={(e) =>
                  setTutors(
                    e.target.checked ? [...tutors, tutor.id] : tutors.filter((x) => x !== tutor.id),
                  )
                }
              />
              {[tutor.first_name, tutor.last_name].filter(Boolean).join(" ")}
            </label>
          ))}
        </div>
      </fieldset>
      <div className="flex flex-wrap gap-3">
        <TextField
          label={t("proposals.deposit")}
          hint={t("proposals.depositHint")}
          inputMode="decimal"
          value={deposit}
          error={errors.deposit}
          onChange={(e) => setDeposit(e.target.value)}
        />
        <TextField
          label={t("proposals.validDays")}
          type="number"
          min={1}
          max={90}
          value={validDays}
          onChange={(e) => setValidDays(e.target.value)}
        />
      </div>
      {save.error && !Object.keys(errors).length ? (
        <Alert tone="danger">{save.error.message}</Alert>
      ) : null}
      <div className="flex gap-2">
        <Button type="submit" disabled={save.isPending}>
          {t("proposals.saveDraft")}
        </Button>
        <Button type="button" variant="ghost" onClick={onDone}>
          {t("common.cancel")}
        </Button>
      </div>
    </form>
  );
}

/** E17-T09: proposals on an enquiry (drafts, sending, the family's answer). */
export function ProposalsSection({ enquiryId }: { enquiryId: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const canManage = usePermission("leads.proposal.manage");
  const [editing, setEditing] = useState<Proposal | "new" | null>(null);
  const proposals = useQuery({
    queryKey: ["proposals", enquiryId],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/proposals", { params: { query: { enquiry: enquiryId } } })),
  });
  const refresh = () => {
    setEditing(null);
    void queryClient.invalidateQueries({ queryKey: ["proposals", enquiryId] });
  };
  const act = useMutation({
    mutationFn: async ({ id, action }: { id: string; action: "send" | "withdraw" }) =>
      action === "send"
        ? unwrap(await api.POST("/api/v1/proposals/{id}/send", { params: { path: { id } } }))
        : unwrap(await api.POST("/api/v1/proposals/{id}/withdraw", { params: { path: { id } } })),
    onSuccess: refresh,
  });
  const rows = proposals.data?.results ?? [];
  return (
    <Panel
      title={t("proposals.title")}
      flush
      aside={
        canManage && editing === null ? (
          <Button size="sm" variant="secondary" onClick={() => setEditing("new")}>
            {t("proposals.new")}
          </Button>
        ) : null
      }
    >
      {proposals.isLoading ? (
        <div className="px-5 py-4">
          <Spinner label={t("grid.loading")} />
        </div>
      ) : null}
      {rows.length === 0 && proposals.data ? (
        <p className="px-5 py-4 text-sm text-muted-foreground">{t("proposals.none")}</p>
      ) : null}
      <PanelRows>
        {rows.map((p) => (
          <PanelRow key={p.id} className="space-y-0.5">
            <p className="font-medium">
              {p.number} · {p.title}
            </p>
            <p className="text-xs text-muted-foreground tabular-nums">
              {t(`proposals.states.${p.state}`)} · {formatMoney(p.total)}
              {p.deposit
                ? ` · ${t("proposals.depositOf", { amount: formatMoney(p.deposit) })}`
                : ""}
              {p.expires_at && p.state === "sent"
                ? ` · ${t("proposals.until", { date: formatDate(p.expires_at) })}`
                : ""}
            </p>
            {p.accepted_name ? (
              <p className="text-xs">
                {t("proposals.acceptedBy", { name: p.accepted_name })}
                {p.chosen_tutor_name
                  ? ` · ${t("proposals.chose", { tutor: p.chosen_tutor_name })}`
                  : ""}
              </p>
            ) : null}
            {p.decline_reason ? (
              <p className="text-xs">
                {t("proposals.declinedBecause", { reason: p.decline_reason })}
              </p>
            ) : null}
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2 pt-1.5">
              <a
                className="font-medium text-link underline-offset-2 hover:underline"
                href={`/api/v1/proposals/${p.id}/pdf`}
                target="_blank"
                rel="noreferrer"
              >
                {t("proposals.pdf")}
              </a>
              {p.link ? (
                <a
                  className="font-medium text-link underline-offset-2 hover:underline"
                  href={p.link}
                  target="_blank"
                  rel="noreferrer"
                >
                  {t("proposals.familyLink")}
                </a>
              ) : null}
              {canManage && p.state === "draft" ? (
                <>
                  <Button size="sm" variant="secondary" onClick={() => setEditing(p)}>
                    {t("proposals.edit")}
                  </Button>
                  <Button size="sm" onClick={() => act.mutate({ id: p.id, action: "send" })}>
                    {t("proposals.send")}
                  </Button>
                </>
              ) : null}
              {canManage && (p.state === "draft" || p.state === "sent") ? (
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => act.mutate({ id: p.id, action: "withdraw" })}
                >
                  {t("proposals.withdraw")}
                </Button>
              ) : null}
            </div>
          </PanelRow>
        ))}
      </PanelRows>
      {act.error ? (
        <div className="px-5 pb-4">
          <Alert tone="danger">{act.error.message}</Alert>
        </div>
      ) : null}
      {editing !== null ? (
        <ProposalEditor
          enquiryId={enquiryId}
          proposal={editing === "new" ? null : editing}
          onDone={refresh}
        />
      ) : null}
    </Panel>
  );
}

/** The family's view: read, choose a tutor, accept by typing their name, or decline. */
export function PublicProposalPage({ token }: { token: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [tutor, setTutor] = useState("");
  const [name, setName] = useState("");
  const [declining, setDeclining] = useState(false);
  const [reason, setReason] = useState("");
  const proposal = useQuery({
    queryKey: ["public-proposal", token],
    queryFn: async () =>
      unwrap(await api.GET("/api/v1/public/proposals/{token}", { params: { path: { token } } })),
    retry: false,
  });
  const accept = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/public/proposals/{token}", {
          params: { path: { token } },
          body: { name, tutor: tutor || null },
        }),
      ),
    onSuccess: (data) => {
      queryClient.setQueryData(["public-proposal", token], data);
      if (data.pay_url) window.location.assign(data.pay_url);
    },
  });
  const decline = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/public/proposals/{token}/decline", {
          params: { path: { token } },
          body: { reason },
        }),
      ),
    onSuccess: (data) => queryClient.setQueryData(["public-proposal", token], data),
  });
  if (proposal.isError) return <PublicLayout title={t("proposals.missing")}>{null}</PublicLayout>;
  if (!proposal.data) return <PublicLayout wide loading />;
  const p = proposal.data;
  const money = (amount: string) => formatMoney({ amount, currency: p.currency });
  const errors = fieldErrors(accept.error);
  return (
    <PublicLayout title={p.title} subtitle={p.number} wide>
      <div className="space-y-6">
        {p.introduction ? <p className="whitespace-pre-line">{p.introduction}</p> : null}
        {p.tutors.length ? (
          <section aria-labelledby="proposal-tutors" className="space-y-2">
            <h2 id="proposal-tutors" className="text-base font-semibold">
              {p.tutors.length > 1 ? t("proposals.chooseTutor") : t("proposals.yourTutor")}
            </h2>
            <div className="grid gap-3">
              {p.tutors.map((card) => (
                <TutorCard
                  key={card.id}
                  card={card}
                  selectable={p.status === "sent" && p.tutors.length > 1}
                  selected={tutor === card.id || p.chosen_tutor === card.id}
                  name="proposal-tutor"
                  onSelect={() => setTutor(card.id)}
                />
              ))}
            </div>
          </section>
        ) : null}
        {p.schedule ? (
          <section className="space-y-1">
            <h2 className="text-base font-semibold">{t("proposals.schedule")}</h2>
            <p className="whitespace-pre-line">{p.schedule}</p>
          </section>
        ) : null}
        <div
          role="region"
          aria-label={t("proposals.pricing")}
          tabIndex={0}
          className="relative overflow-x-auto rounded-xl border border-border bg-surface"
        >
          <table className="w-full text-sm [&_td]:px-4 [&_td]:py-2.5 [&_th]:px-4 [&_th]:py-2.5">
            <caption className="border-b border-border px-4 py-3 text-left text-base font-semibold">
              {t("proposals.pricing")}
            </caption>
            <thead className="border-b border-border">
              <tr className="text-left">
                <th scope="col">{t("proposals.description")}</th>
                <th scope="col" className="text-right">
                  {t("proposals.quantity")}
                </th>
                <th scope="col" className="text-right">
                  {t("proposals.unitPrice")}
                </th>
                <th scope="col" className="text-right">
                  {t("proposals.amount")}
                </th>
              </tr>
            </thead>
            <tbody>
              {p.lines.map((line, i) => (
                <tr key={i}>
                  <td>{line.description}</td>
                  <td className="text-right">{line.quantity}</td>
                  <td className="text-right">{money(line.unit_price)}</td>
                  <td className="text-right">{money(line.amount)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t border-border font-semibold">
                <th scope="row" colSpan={3} className="text-left">
                  {t("proposals.total")}
                </th>
                <td className="text-right">{money(p.total)}</td>
              </tr>
              {p.deposit ? (
                <tr className="border-t border-rule">
                  <th scope="row" colSpan={3} className="text-left font-normal">
                    {t("proposals.depositDue")}
                  </th>
                  <td className="text-right">{money(p.deposit)}</td>
                </tr>
              ) : null}
            </tfoot>
          </table>
        </div>
        {p.terms ? (
          <details className="group">
            <summary className="flex cursor-pointer list-none items-center gap-1.5 text-sm font-medium [&::-webkit-details-marker]:hidden">
              <ChevronRight
                aria-hidden="true"
                strokeWidth={1.75}
                className="size-4 text-muted-foreground transition-transform duration-150 group-open:rotate-90"
              />
              {t("proposals.terms")}
            </summary>
            <p className="mt-2 pl-5.5 text-sm whitespace-pre-line text-muted-foreground">
              {p.terms}
            </p>
          </details>
        ) : null}
        <p className="text-sm">
          <a
            className="font-medium text-link underline-offset-2 hover:underline"
            href={`/api/v1/public/proposals/${token}/pdf`}
            target="_blank"
            rel="noreferrer"
          >
            {t("proposals.downloadPdf")}
          </a>
        </p>
        {p.status === "sent" ? (
          <>
            {p.expires_at ? (
              <p className="text-sm text-muted-foreground">
                {t("proposals.until", { date: formatDate(p.expires_at) })}
              </p>
            ) : null}
            <form
              className="space-y-3 rounded-xl border border-border bg-surface px-5 py-4"
              aria-label={t("proposals.acceptForm")}
              onSubmit={(e) => {
                e.preventDefault();
                accept.mutate();
              }}
            >
              <TextField
                label={t("proposals.signName")}
                hint={t("proposals.signHint")}
                autoComplete="name"
                value={name}
                error={errors.name ?? errors.tutor}
                onChange={(e) => setName(e.target.value)}
              />
              <div className="flex flex-wrap items-center gap-2">
                <Button type="submit" disabled={accept.isPending || name.trim().length < 2}>
                  {p.deposit ? t("proposals.acceptAndPay") : t("proposals.accept")}
                </Button>
                {declining ? null : (
                  <Button
                    type="button"
                    variant="ghost"
                    className="text-muted-foreground"
                    onClick={() => setDeclining(true)}
                  >
                    {t("proposals.notForUs")}
                  </Button>
                )}
              </div>
            </form>
            {accept.error && !Object.keys(errors).length ? (
              <Alert tone="danger">{accept.error.message}</Alert>
            ) : null}
            {declining ? (
              <form
                className="space-y-3 rounded-xl border border-border bg-surface px-5 py-4"
                aria-label={t("proposals.declineForm")}
                onSubmit={(e) => {
                  e.preventDefault();
                  decline.mutate();
                }}
              >
                <TextField
                  label={t("proposals.declineReason")}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                />
                <Button type="submit" variant="secondary">
                  {t("proposals.decline")}
                </Button>
              </form>
            ) : null}
          </>
        ) : (
          <div role="status" className="space-y-2">
            <p>{t(`proposals.publicStates.${p.status}`)}</p>
            {p.pay_url ? (
              <a
                className="font-medium text-link underline-offset-2 hover:underline"
                href={p.pay_url}
              >
                {t("proposals.payDeposit")}
              </a>
            ) : null}
          </div>
        )}
      </div>
    </PublicLayout>
  );
}
