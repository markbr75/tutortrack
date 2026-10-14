import { useTranslation } from "@tutortrack/i18n";
import { useNavigate, useRouterState } from "@tanstack/react-router";
import { useCallback, useEffect, useRef, useState } from "react";

import { useMe } from "../api";
import { routePattern, setOrganisationAllowsAnalytics, track } from "./analytics";
import { useGuidance, useTourStatus } from "./guidance";
import { HelpPanel } from "./HelpPanel";
import { NpsPrompt } from "./NpsPrompt";
import { Tour } from "./Tour";
import { tourByKey, type TourDefinition } from "./tours";

/**
 * The in-app help layer (E30 Part 2), mounted once in the admin shell: the Help button
 * (with a dot for unread "What's new" entries and support replies), the help panel,
 * product tours, the NPS prompt and consent-gated page-view tracking.
 */
export function SuccessLayer() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const me = useMe();
  const impersonating = Boolean(me.data?.impersonator);
  const guidance = useGuidance(Boolean(me.data));
  const tourStatus = useTourStatus();
  const pathname = useRouterState({ select: (s) => s.location.pathname });
  const [panelOpen, setPanelOpen] = useState(false);
  const helpButton = useRef<HTMLButtonElement>(null);
  const [tour, setTour] = useState<TourDefinition | null>(null);
  const [npsOpen, setNpsOpen] = useState(false);
  const [offeredWelcome, setOfferedWelcome] = useState(false);
  const data = guidance.data;

  useEffect(() => {
    setOrganisationAllowsAnalytics(Boolean(data?.analytics_allowed));
  }, [data?.analytics_allowed]);

  useEffect(() => {
    if (data) track("page.viewed", undefined, routePattern(pathname));
  }, [pathname, data]);

  useEffect(() => {
    if (data?.nps_due && !impersonating) setNpsOpen(true);
  }, [data?.nps_due, impersonating]);

  // New members get the welcome tour once, on the dashboard.
  useEffect(() => {
    if (!data || offeredWelcome || impersonating || pathname !== "/") return;
    setOfferedWelcome(true);
    const seen = [...data.completed_tours, ...data.dismissed_tours];
    if (!seen.includes("welcome")) setTour(tourByKey("welcome") ?? null);
  }, [data, offeredWelcome, impersonating, pathname]);

  const startTour = useCallback(
    (key: string) => {
      const next = tourByKey(key);
      if (!next) return;
      setPanelOpen(false);
      helpButton.current?.focus(); // where focus returns when the tour ends
      track("tour.started", { tour: key });
      if (pathname === next.path) setTour(next);
      else void navigate({ to: next.path as "/" }).then(() => setTour(next));
    },
    [navigate, pathname],
  );

  const finishTour = useCallback(
    (outcome: "completed" | "dismissed") => {
      if (tour) {
        track(`tour.${outcome}`, { tour: tour.key });
        if (!impersonating) tourStatus.mutate({ key: tour.key, status: outcome });
      }
      setTour(null);
    },
    [tour, tourStatus, impersonating],
  );

  const unread = (data?.changelog_unread ?? 0) + (data?.support_unread ?? 0);
  return (
    <>
      <button
        ref={helpButton}
        type="button"
        data-tour="help"
        onClick={() => setPanelOpen(true)}
        aria-haspopup="dialog"
        className="relative rounded-md px-2 py-1 text-left text-sm hover:bg-muted"
      >
        {t("help.open")}
        {unread > 0 ? (
          <>
            <span aria-hidden="true" className="ml-1 inline-block size-2 rounded-full bg-brand" />
            <span className="sr-only">{t("help.unread", { count: unread })}</span>
          </>
        ) : null}
      </button>
      {panelOpen ? (
        <HelpPanel
          open
          onClose={() => {
            setPanelOpen(false);
            helpButton.current?.focus();
          }}
          onStartTour={startTour}
          initialTab={data?.support_unread ? "support" : "articles"}
        />
      ) : null}
      {tour ? <Tour key={tour.key} tour={tour} onFinish={finishTour} /> : null}
      {npsOpen && !tour ? <NpsPrompt onClose={() => setNpsOpen(false)} /> : null}
    </>
  );
}
