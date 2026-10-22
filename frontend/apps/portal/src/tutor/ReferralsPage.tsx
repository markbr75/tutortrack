import { unwrap } from "@tutortrack/api-client";
import { formatDate, formatMoney, useTranslation } from "@tutortrack/i18n";
import { Alert, PanelRow, PanelRows, RuledPanel, Spinner } from "@tutortrack/ui";
import { useQuery } from "@tanstack/react-query";

import { api } from "../api";
import { PanelEmpty, PortalHeader, Word } from "../layout/PortalPage";
import { CopyLink } from "../pages/ReferralsPage";

/** FR-25-4: a tutor's referral links (families and tutors) and bonuses earned. */
export function TutorReferralsPage() {
  const { t, i18n } = useTranslation();
  const page = useQuery({
    queryKey: ["portal", "tutor", "referrals"],
    queryFn: async () => unwrap(await api.GET("/api/v1/portal/tutor/referrals")),
  });
  if (page.isPending) return <Spinner label={t("grid.loading")} />;
  if (!page.data) return <Alert>{t("referrals.portal.unavailable")}</Alert>;
  const p = page.data;
  return (
    <div>
      <PortalHeader
        title={t("referrals.tutorPortal.title")}
        description={t("referrals.tutorPortal.intro")}
      />
      <div className="space-y-6">
        <RuledPanel label={t("referrals.tutorPortal.title")}>
          <div className="space-y-4">
            <CopyLink label={t("referrals.tutorPortal.families")} url={p.client_link} />
            <CopyLink label={t("referrals.tutorPortal.tutors")} url={p.tutor_link} />
          </div>
        </RuledPanel>
        <RuledPanel title={t("designS10.peopleYouReferred")} flush>
          {p.referrals.length ? (
            <PanelRows>
              {p.referrals.map((r) => (
                <PanelRow key={r.id} className="flex items-baseline justify-between gap-4">
                  <div className="min-w-0">
                    <p className="font-medium">
                      {r.referred_name} · {t(`referrals.tutorKinds.${r.kind}`)}
                    </p>
                    <p className="text-xs text-muted-foreground tabular-nums">
                      <Word
                        tone={r.status === "pending" ? "margin" : "ink"}
                        className={r.status === "pending" ? "" : "text-foreground"}
                      >
                        {t(`referrals.tutorStatus.${r.status}`)}
                      </Word>{" "}
                      · {formatDate(r.created_at, i18n.language)}
                    </p>
                  </div>
                  {r.bonus ? (
                    <p className="w-28 shrink-0 text-right font-semibold tabular-nums">
                      {formatMoney(r.bonus, i18n.language)}
                    </p>
                  ) : null}
                </PanelRow>
              ))}
            </PanelRows>
          ) : (
            <PanelEmpty>{t("referrals.portal.none")}</PanelEmpty>
          )}
        </RuledPanel>
      </div>
    </div>
  );
}
