import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { api, usePortalMe } from "../api";

type Relationship = components["schemas"]["GuardianInviteRequest"]["relationship"];
type StudentLogin = components["schemas"]["StudentLogin"];

function errorsOf(error: unknown): Record<string, string> {
  const extra = (error as { problem?: { errors?: Record<string, string[]> } } | null)?.problem;
  return Object.fromEntries(
    Object.entries(extra?.errors ?? {}).map(([k, v]) => [k, String(Array.isArray(v) ? v[0] : v)]),
  );
}

/** Invite another guardian (FR-15-8). */
function Guardians() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const confirmId = useId();
  const blank = {
    first_name: "",
    last_name: "",
    email: "",
    relationship: "guardian" as Relationship,
  };
  const [form, setForm] = useState(blank);
  const [confirm, setConfirm] = useState(false);
  const guardians = useQuery({
    queryKey: ["portal", "guardians"],
    queryFn: async () => unwrap(await api.GET("/api/v1/portal/guardians")),
  });
  const invite = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/v1/portal/guardians", { body: { ...form, confirm } })),
    onSuccess: () => {
      setForm(blank);
      setConfirm(false);
      void queryClient.invalidateQueries({ queryKey: ["portal", "guardians"] });
    },
  });
  const errors = errorsOf(invite.error);
  return (
    <section aria-labelledby="guardians-title" className="space-y-3">
      <h2 id="guardians-title" className="text-lg font-medium">
        {t("family.guardiansTitle")}
      </h2>
      {guardians.isPending ? <Spinner label={t("grid.loading")} /> : null}
      <ul className="divide-y divide-border rounded-lg border border-border text-sm">
        {(guardians.data ?? []).map((g) => (
          <li key={g.id} className="flex flex-wrap justify-between gap-2 p-3">
            <span>{g.name}</span>
            <span className="text-muted-foreground">{t(`family.portal.${g.portal}`)}</span>
          </li>
        ))}
      </ul>
      <form
        className="grid gap-3 sm:grid-cols-2"
        aria-label={t("family.inviteTitle")}
        onSubmit={(e) => {
          e.preventDefault();
          invite.mutate();
        }}
      >
        <TextField
          label={t("family.firstName")}
          required
          value={form.first_name}
          error={errors.first_name}
          onChange={(e) => setForm((f) => ({ ...f, first_name: e.target.value }))}
        />
        <TextField
          label={t("family.lastName")}
          value={form.last_name}
          onChange={(e) => setForm((f) => ({ ...f, last_name: e.target.value }))}
        />
        <TextField
          label={t("family.email")}
          type="email"
          required
          value={form.email}
          error={errors.email}
          onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
        />
        <SelectField
          label={t("family.relationship")}
          value={form.relationship}
          options={(["parent", "guardian", "carer", "other"] as const).map((r) => ({
            value: r,
            label: t(`family.relationships.${r}`),
          }))}
          onChange={(e) => setForm((f) => ({ ...f, relationship: e.target.value as Relationship }))}
        />
        <div className="flex items-start gap-2 text-sm sm:col-span-2">
          <input
            id={confirmId}
            type="checkbox"
            className="mt-1"
            checked={confirm}
            onChange={(e) => setConfirm(e.target.checked)}
          />
          <label htmlFor={confirmId}>{t("family.confirm")}</label>
        </div>
        {invite.isError && !Object.keys(errors).length ? (
          <Alert tone="danger">{invite.error.message}</Alert>
        ) : null}
        {errors.confirm ? <Alert tone="danger">{errors.confirm}</Alert> : null}
        {invite.isSuccess ? <Alert tone="success">{t("family.invited")}</Alert> : null}
        <div className="sm:col-span-2">
          <Button type="submit" loading={invite.isPending} disabled={!confirm}>
            {t("family.invite")}
          </Button>
        </div>
      </form>
    </section>
  );
}

function LoginRow({ row }: { row: StudentLogin }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const consentId = useId();
  const [username, setUsername] = useState("");
  const [pin, setPin] = useState("");
  const [consent, setConsent] = useState(false);
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["portal", "logins"] });
  const create = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/portal/student-logins", {
          body: { student_id: row.student_id, username, pin, parental_consent: consent },
        }),
      ),
    onSuccess: () => {
      setPin("");
      refresh();
    },
  });
  const changePin = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/portal/student-logins/{student_id}/pin", {
          params: { path: { student_id: row.student_id } },
          body: { pin },
        }),
      ),
    onSuccess: () => {
      setPin("");
      refresh();
    },
  });
  const remove = useMutation({
    mutationFn: async () =>
      api.DELETE("/api/v1/portal/student-logins/{student_id}", {
        params: { path: { student_id: row.student_id } },
      }),
    onSuccess: refresh,
  });
  const errors = { ...errorsOf(create.error), ...errorsOf(changePin.error) };
  const failure = create.error ?? changePin.error;
  return (
    <li className="space-y-3 p-3">
      <p className="font-medium">{row.student_name}</p>
      {row.username ? (
        <>
          <p className="text-sm">
            {t("family.loginActive", {
              username: row.username,
              when: row.pin_changed_at ? formatDateTime(row.pin_changed_at, i18n.language) : "",
            })}
          </p>
          <form
            className="flex flex-wrap items-end gap-2"
            aria-label={t("family.changePinFor", { name: row.student_name })}
            onSubmit={(e) => {
              e.preventDefault();
              changePin.mutate();
            }}
          >
            <TextField
              label={t("family.newPin")}
              type="password"
              autoComplete="new-password"
              inputMode="numeric"
              value={pin}
              error={errors.pin}
              onChange={(e) => setPin(e.target.value)}
            />
            <Button type="submit" size="sm" loading={changePin.isPending}>
              {t("family.changePin")}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="danger"
              loading={remove.isPending}
              onClick={() => remove.mutate()}
            >
              {t("family.removeLogin")}
            </Button>
          </form>
          {changePin.isSuccess ? <Alert tone="success">{t("family.pinChanged")}</Alert> : null}
        </>
      ) : row.has_email_login ? (
        <p className="text-sm text-muted-foreground">{t("family.hasEmailLogin")}</p>
      ) : !row.eligible ? (
        <p className="text-sm text-muted-foreground">{t("family.notEligible")}</p>
      ) : (
        <form
          className="grid gap-3 sm:grid-cols-2"
          aria-label={t("family.createFor", { name: row.student_name })}
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <TextField
            label={t("family.username")}
            autoComplete="off"
            hint={t("family.usernameHint")}
            required
            value={username}
            error={errors.username}
            onChange={(e) => setUsername(e.target.value)}
          />
          <TextField
            label={t("family.pin")}
            type="password"
            autoComplete="new-password"
            hint={t("family.pinHint")}
            required
            value={pin}
            error={errors.pin}
            onChange={(e) => setPin(e.target.value)}
          />
          <div className="flex items-start gap-2 text-sm sm:col-span-2">
            <input
              id={consentId}
              type="checkbox"
              className="mt-1"
              checked={consent}
              onChange={(e) => setConsent(e.target.checked)}
            />
            <label htmlFor={consentId}>{t("family.consent", { name: row.student_name })}</label>
          </div>
          <div className="sm:col-span-2">
            <Button type="submit" size="sm" loading={create.isPending} disabled={!consent}>
              {t("family.createLogin")}
            </Button>
          </div>
        </form>
      )}
      {failure && !Object.keys(errors).length ? (
        <Alert tone="danger">{failure.message}</Alert>
      ) : null}
    </li>
  );
}

/** Guardian-managed logins for children under 13 (FR-15-1). */
function StudentLogins() {
  const { t } = useTranslation();
  const logins = useQuery({
    queryKey: ["portal", "logins"],
    queryFn: async () => unwrap(await api.GET("/api/v1/portal/student-logins")),
  });
  return (
    <section aria-labelledby="logins-title" className="space-y-3">
      <h2 id="logins-title" className="text-lg font-medium">
        {t("family.loginsTitle")}
      </h2>
      <p className="text-sm text-muted-foreground">{t("family.loginsIntro")}</p>
      {logins.isPending ? <Spinner label={t("grid.loading")} /> : null}
      <ul className="divide-y divide-border rounded-lg border border-border">
        {(logins.data ?? []).map((row) => (
          <LoginRow key={row.student_id} row={row} />
        ))}
      </ul>
    </section>
  );
}

export function FamilyPage() {
  const { t } = useTranslation();
  const me = usePortalMe();
  const f = me.data?.features;
  return (
    <div className="space-y-8">
      <h1 className="text-xl font-semibold">{t("family.title")}</h1>
      {f?.guardian_invites ? <Guardians /> : null}
      {f?.student_logins ? <StudentLogins /> : null}
    </div>
  );
}
