import { unwrap } from "@tutortrack/api-client";
import { formatDate, useTranslation } from "@tutortrack/i18n";
import { Alert, Button, SelectField } from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";

import { api } from "../api";

/** "Your data" (E29-T05): ask for a copy of your (or your child's) data, or for it to be
 * erased, and follow the request. The copy arrives as an expiring link by email. */
export function PrivacyPage() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
  const id = useId();
  const requests = useQuery({
    queryKey: ["portal", "data-requests"],
    queryFn: async () => unwrap(await api.GET("/api/v1/me/data-requests")),
  });
  const profile = useQuery({
    queryKey: ["portal", "profile"],
    queryFn: async () => unwrap(await api.GET("/api/v1/portal/profile")),
    retry: false,
  });
  const [kind, setKind] = useState("access");
  const [who, setWho] = useState("");
  const [details, setDetails] = useState("");
  const create = useMutation({
    mutationFn: async () =>
      unwrap(
        await api.POST("/api/v1/me/data-requests", {
          body: {
            kind: kind as "access",
            details,
            ...(who ? { student_id: who } : {}),
          },
        }),
      ),
    onSuccess: () => {
      setDetails("");
      void queryClient.invalidateQueries({ queryKey: ["portal", "data-requests"] });
    },
  });
  const children = profile.data?.students ?? [];
  return (
    <section className="space-y-6 p-4">
      <h1 className="text-2xl font-semibold">{t("privacyCentre.portal.title")}</h1>
      <p className="text-sm text-muted-foreground">{t("privacyCentre.portal.intro")}</p>
      <form
        className="space-y-3 rounded-md border border-border p-4"
        aria-label={t("privacyCentre.portal.newRequest")}
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate();
        }}
      >
        <h2 className="font-semibold">{t("privacyCentre.portal.newRequest")}</h2>
        <SelectField
          label={t("privacyCentre.portal.what")}
          value={kind}
          onChange={(e) => setKind(e.target.value)}
          options={["access", "portability", "erasure"].map((k) => ({
            value: k,
            label: t(`privacyCentre.portal.kinds.${k}`),
          }))}
        />
        {children.length ? (
          <SelectField
            label={t("privacyCentre.portal.about")}
            value={who}
            onChange={(e) => setWho(e.target.value)}
            options={[
              { value: "", label: t("privacyCentre.portal.me") },
              ...children.map((c) => ({
                value: c.id,
                label: `${c.preferred_name || c.first_name} ${c.last_name}`,
              })),
            ]}
          />
        ) : null}
        <div className="flex flex-col gap-1">
          <label htmlFor={`${id}-details`} className="text-sm font-medium">
            {t("privacyCentre.portal.details")}
          </label>
          <textarea
            id={`${id}-details`}
            rows={3}
            className="rounded-md border border-border bg-background p-2 text-sm"
            value={details}
            onChange={(e) => setDetails(e.target.value)}
          />
        </div>
        {kind === "erasure" ? (
          <Alert tone="warning">{t("privacyCentre.portal.erasureWarning")}</Alert>
        ) : null}
        {create.error ? <Alert tone="danger">{create.error.message}</Alert> : null}
        {create.isSuccess ? (
          <Alert tone="success">
            {t("privacyCentre.portal.sent", {
              reference: create.data.reference,
              date: formatDate(create.data.due_at, i18n.language),
            })}
          </Alert>
        ) : null}
        <Button type="submit" disabled={create.isPending}>
          {t("privacyCentre.portal.send")}
        </Button>
      </form>
      {requests.data?.length ? (
        <section aria-labelledby={`${id}-mine`}>
          <h2 id={`${id}-mine`} className="mb-2 font-semibold">
            {t("privacyCentre.portal.yourRequests")}
          </h2>
          <ul className="space-y-2 text-sm">
            {requests.data.map((r) => (
              <li key={r.id} className="rounded-md border border-border p-3">
                <p className="font-medium">
                  {r.reference} · {t(`privacyCentre.portal.kinds.${r.kind}`)}
                </p>
                <p>
                  {t(`privacyCentre.statuses.${r.status}`)} ·{" "}
                  {t("privacyCentre.portal.answerBy", {
                    date: formatDate(r.due_at, i18n.language),
                  })}
                </p>
                {r.close_reason ? <p className="text-muted-foreground">{r.close_reason}</p> : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </section>
  );
}
