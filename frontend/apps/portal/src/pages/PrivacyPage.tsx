import { unwrap } from "@tutortrack/api-client";
import { formatDate, useTranslation } from "@tutortrack/i18n";
import {
  Alert,
  Button,
  PanelFooter,
  PanelRow,
  PanelRows,
  RuledPanel,
  SelectField,
} from "@tutortrack/ui";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api";
import { PortalHeader, TextAreaField } from "../layout/PortalPage";

/** "Your data" (E29-T05): ask for a copy of your (or your child's) data, or for it to be
 * erased, and follow the request. The copy arrives as an expiring link by email. */
export function PrivacyPage() {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();
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
    <div>
      <PortalHeader
        title={t("privacyCentre.portal.title")}
        description={t("privacyCentre.portal.intro")}
      />
      <div className="space-y-6">
        <form
          aria-label={t("privacyCentre.portal.newRequest")}
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <RuledPanel title={t("privacyCentre.portal.newRequest")} flush>
            <div className="grid items-start gap-x-4 gap-y-3 px-5 py-4 sm:grid-cols-2">
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
              <TextAreaField
                className="sm:col-span-2"
                label={t("privacyCentre.portal.details")}
                value={details}
                onChange={(e) => setDetails(e.target.value)}
              />
              {kind === "erasure" ? (
                <Alert tone="warning" className="sm:col-span-2">
                  {t("privacyCentre.portal.erasureWarning")}
                </Alert>
              ) : null}
              {create.error ? (
                <Alert tone="danger" className="sm:col-span-2">
                  {create.error.message}
                </Alert>
              ) : null}
              {create.isSuccess ? (
                <Alert tone="success" className="sm:col-span-2">
                  {t("privacyCentre.portal.sent", {
                    reference: create.data.reference,
                    date: formatDate(create.data.due_at, i18n.language),
                  })}
                </Alert>
              ) : null}
            </div>
            <PanelFooter>
              <Button type="submit" disabled={create.isPending}>
                {t("privacyCentre.portal.send")}
              </Button>
            </PanelFooter>
          </RuledPanel>
        </form>
        {requests.data?.length ? (
          <RuledPanel title={t("privacyCentre.portal.yourRequests")} flush>
            <PanelRows>
              {requests.data.map((r) => (
                <PanelRow key={r.id}>
                  <p className="font-medium">
                    <span className="tabular-nums">{r.reference}</span> ·{" "}
                    {t(`privacyCentre.portal.kinds.${r.kind}`)}
                  </p>
                  <p className="text-xs text-muted-foreground tabular-nums">
                    <span className="text-foreground">
                      {t(`privacyCentre.statuses.${r.status}`)}
                    </span>{" "}
                    ·{" "}
                    {t("privacyCentre.portal.answerBy", {
                      date: formatDate(r.due_at, i18n.language),
                    })}
                    {r.close_reason ? ` · ${r.close_reason}` : ""}
                  </p>
                </PanelRow>
              ))}
            </PanelRows>
          </RuledPanel>
        ) : null}
      </div>
    </div>
  );
}
