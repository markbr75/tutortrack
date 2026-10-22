import { unwrap, type components } from "@tutortrack/api-client";
import { formatDateTime, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  CheckboxField,
  NamePlate,
  PanelFooter,
  PanelRow,
  PanelRows,
  RuledPanel,
  SelectField,
  TextField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api, usePortalMe } from "../api";
import { PanelEmpty, PanelLoading, PortalHeader } from "../layout/PortalPage";

type Relationship = components["schemas"]["GuardianInviteRequest"]["relationship"];
type StudentLogin = components["schemas"]["StudentLogin"];

const quiet = "text-muted-foreground hover:text-foreground";

function errorsOf(error: unknown): Record<string, string> {
  const extra = (error as { problem?: { errors?: Record<string, string[]> } } | null)?.problem;
  return Object.fromEntries(
    Object.entries(extra?.errors ?? {}).map(([k, v]) => [k, String(Array.isArray(v) ? v[0] : v)]),
  );
}

/** The household's guardians as ruled rows, then the invite form in the same panel (FR-15-8). */
function Guardians() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
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
    <div className="space-y-6">
      <RuledPanel title={t("family.guardiansTitle")} flush>
        {guardians.isPending ? (
          <PanelLoading label={t("grid.loading")} />
        ) : guardians.data?.length ? (
          <PanelRows>
            {guardians.data.map((g) => (
              <PanelRow key={g.id}>
                <NamePlate
                  name={g.name}
                  aside={
                    <span className="text-sm text-muted-foreground">
                      {t(`family.portal.${g.portal}`)}
                    </span>
                  }
                />
              </PanelRow>
            ))}
          </PanelRows>
        ) : (
          <PanelEmpty>{t("designS10.noGuardians")}</PanelEmpty>
        )}
      </RuledPanel>
      <form
        aria-label={t("family.inviteTitle")}
        onSubmit={(e) => {
          e.preventDefault();
          invite.mutate();
        }}
      >
        <RuledPanel title={t("family.inviteTitle")} flush>
          <div className="grid items-start gap-x-4 gap-y-3 px-5 py-4 sm:grid-cols-2">
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
              onChange={(e) =>
                setForm((f) => ({ ...f, relationship: e.target.value as Relationship }))
              }
            />
            <CheckboxField
              className="sm:col-span-2"
              label={t("family.confirm")}
              checked={confirm}
              onChange={(e) => setConfirm(e.target.checked)}
            />
            {invite.isError && !Object.keys(errors).length ? (
              <Alert tone="danger" className="sm:col-span-2">
                {invite.error.message}
              </Alert>
            ) : null}
            {errors.confirm ? (
              <Alert tone="danger" className="sm:col-span-2">
                {errors.confirm}
              </Alert>
            ) : null}
            {invite.isSuccess ? (
              <Alert tone="success" className="sm:col-span-2">
                {t("family.invited")}
              </Alert>
            ) : null}
          </div>
          <PanelFooter>
            <Button type="submit" loading={invite.isPending} disabled={!confirm}>
              {t("family.invite")}
            </Button>
          </PanelFooter>
        </RuledPanel>
      </form>
    </div>
  );
}

function LoginRow({ row }: { row: StudentLogin }) {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
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
  const context = row.username
    ? t("family.loginActive", {
        username: row.username,
        when: row.pin_changed_at ? formatDateTime(row.pin_changed_at, i18n.language) : "",
      })
    : row.has_email_login
      ? t("family.hasEmailLogin")
      : !row.eligible
        ? t("family.notEligible")
        : undefined;
  return (
    <li className="space-y-3 px-5 py-3.5">
      <NamePlate name={row.student_name} context={context} />
      {row.username ? (
        <>
          <form
            className="flex flex-wrap items-end gap-2"
            aria-label={t("family.changePinFor", { name: row.student_name })}
            onSubmit={(e) => {
              e.preventDefault();
              changePin.mutate();
            }}
          >
            <TextField
              size="sm"
              label={t("family.newPin")}
              type="password"
              autoComplete="new-password"
              inputMode="numeric"
              value={pin}
              error={errors.pin}
              onChange={(e) => setPin(e.target.value)}
            />
            <Button type="submit" size="sm" variant="secondary" loading={changePin.isPending}>
              {t("family.changePin")}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className={quiet}
              loading={remove.isPending}
              onClick={() => remove.mutate()}
            >
              {t("family.removeLogin")}
            </Button>
          </form>
          {changePin.isSuccess ? <Alert tone="success">{t("family.pinChanged")}</Alert> : null}
        </>
      ) : row.has_email_login || !row.eligible ? null : (
        <form
          className="grid items-start gap-x-4 gap-y-3 sm:grid-cols-2"
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
          <CheckboxField
            className="sm:col-span-2"
            label={t("family.consent", { name: row.student_name })}
            checked={consent}
            onChange={(e) => setConsent(e.target.checked)}
          />
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
    <RuledPanel title={t("family.loginsTitle")} description={t("family.loginsIntro")} flush>
      {logins.isPending ? (
        <PanelLoading label={t("grid.loading")} />
      ) : (
        <ul className="divide-y divide-rule">
          {(logins.data ?? []).map((row) => (
            <LoginRow key={row.student_id} row={row} />
          ))}
        </ul>
      )}
    </RuledPanel>
  );
}

export function FamilyPage() {
  const { t } = useTranslation();
  const me = usePortalMe();
  const f = me.data?.features;
  return (
    <div>
      <PortalHeader title={t("family.title")} />
      <div className="space-y-6">
        {f?.guardian_invites ? <Guardians /> : null}
        {f?.student_logins ? <StudentLogins /> : null}
      </div>
    </div>
  );
}
