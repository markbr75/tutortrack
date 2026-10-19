import { unwrap } from "@tutortrack/api-client";
import { formatDate, formatMoney, useTranslation } from "@tutortrack/i18n";
import { Spinner } from "@tutortrack/ui";
import { useQuery } from "@tanstack/react-query";

import { api } from "../api";
import { CopyLink } from "../pages/ReferralsPage";

/** FR-25-4: a tutor's referral links (families and tutors) and bonuses earned. */
export function TutorReferralsPage() {
  const { t, i18n } = useTranslation();
  const page = useQuery({
    queryKey: ["portal", "tutor", "referrals"],
    queryFn: async () => unwrap(await api.GET("/api/v1/portal/tutor/referrals")),
  });
  if (page.isPending) return <Spinner label={t("grid.loading")} />;
  if (!page.data) return <p>{t("referrals.portal.unavailable")}</p>;
  const p = page.data;
  return (
    <section className="space-y-4" aria-labelledby="tutor-referrals">
      <h1 id="tutor-referrals" className="text-xl font-semibold">
        {t("referrals.tutorPortal.title")}
      </h1>
      <p>{t("referrals.tutorPortal.intro")}</p>
      <CopyLink label={t("referrals.tutorPortal.families")} url={p.client_link} />
      <CopyLink label={t("referrals.tutorPortal.tutors")} url={p.tutor_link} />
      {p.referrals.length ? (
        <ul className="space-y-2">
          {p.referrals.map((r) => (
            <li key={r.id} className="rounded-md border border-border p-3 text-sm">
              <p className="font-medium">
                {r.referred_name} · {t(`referrals.tutorKinds.${r.kind}`)}
              </p>
              <p>
                {t(`referrals.tutorStatus.${r.status}`)} · {formatDate(r.created_at, i18n.language)}
                {r.bonus ? ` · ${formatMoney(r.bonus, i18n.language)}` : ""}
              </p>
            </li>
          ))}
        </ul>
      ) : (
        <p>{t("referrals.portal.none")}</p>
      )}
    </section>
  );
}
