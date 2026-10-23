import { useTranslation } from "@tutortrack/i18n";
import { Spinner } from "@tutortrack/ui";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Outlet, useLocation, useNavigate } from "@tanstack/react-router";
import {
  Bell,
  Briefcase,
  CalendarDays,
  CalendarSync,
  Clock,
  FileCheck,
  Gift,
  GraduationCap,
  Library,
  ListChecks,
  MessageSquare,
  NotebookPen,
  ReceiptText,
  ShieldCheck,
  Sun,
  ClipboardCheck,
  UserRound,
  Wallet,
} from "lucide-react";
import { useEffect } from "react";

import { unwrap } from "@tutortrack/api-client";

import { api } from "../api";
import { BrandMark, PoweredBy } from "../branding";
import { PortalFrame } from "../layout/PortalFrame";
import { usePortalBranding } from "../useBranding";
import {
  clearOfflineData,
  useOfflineOwner,
  useOutboxSync,
  useWarmOfflineCache,
} from "../offline/client";
import { OfflineIndicator } from "../offline/OfflineIndicator";
import { useTutorMe } from "./useTutorMe";

/** What waits for the tutor, for the tab bar's count pills: lessons that are over and still
 * to mark (today and earlier days) plus reports to write (on Today), job offers, unread
 * messages and notifications. Shares its caches with Today and Messages. */
function useTutorWaiting(enabled: boolean) {
  const today = useQuery({
    queryKey: ["tutor", "today"],
    enabled,
    refetchInterval: 60_000,
    queryFn: async () => unwrap(await api.GET("/api/v1/tutor/today")),
  });
  const threads = useQuery({
    queryKey: ["portal", "threads", "tutor"],
    enabled,
    refetchInterval: 60_000,
    queryFn: async () => unwrap(await api.GET("/api/v1/tutor/threads")),
  });
  const d = today.data;
  const now = Date.now();
  // The API counts every lesson still to mark over the last 60 days; a response cached
  // before that field existed (offline) falls back to today's lessons.
  const due =
    d?.unmarked_lessons ??
    (d?.lessons ?? []).filter(
      (lesson) => lesson.status === "planned" && new Date(lesson.end).getTime() <= now,
    ).length;
  return {
    toMark: due + (d?.reports_due ?? 0),
    offers: d?.offers ?? 0,
    notifications: d?.unread ?? 0,
    unreadMessages: (threads.data ?? []).reduce((sum, row) => sum + (row.unread ?? 0), 0),
  };
}

/** The tutor's phone-first shell (E16-T01). */
export function TutorShell() {
  const { t } = useTranslation();
  const me = useTutorMe();
  const location = useLocation();
  const navigate = useNavigate();
  useEffect(() => {
    // The in-app classroom (E22-T10) is shared with families, so it lives outside /tutor;
    // gap G5c: the tutor's "Open the classroom" link must not bounce back to Today.
    const shared = location.pathname.startsWith("/classroom/");
    if (!location.pathname.startsWith("/tutor") && !shared) void navigate({ to: "/tutor" });
  }, [location.pathname, navigate]);
  // Offline (E16-T08): replay queued changes, keep the next week on the phone, and never
  // leave one person's data for the next one who signs in here.
  const identity = useQuery({
    queryKey: ["identity", "me"],
    queryFn: async () => (await api.GET("/api/v1/me")).data ?? null,
  });
  useOfflineOwner(identity.data?.user?.id);
  const organisation = usePortalBranding()?.name ?? "";
  useOutboxSync();
  useWarmOfflineCache(Boolean(me.data));
  const logout = useMutation({
    mutationFn: async () => {
      await clearOfflineData();
      return api.POST("/api/v1/auth/logout");
    },
    onSuccess: () => window.location.assign("/portal/"),
  });
  const waiting = useTutorWaiting(Boolean(me.data));
  if (me.isPending) return <Spinner className="p-6" label={t("grid.loading")} />;
  if (!me.data) return <p className="p-6">{t("tutor.noProfile")}</p>;
  const nav = [
    { to: "/tutor", label: t("tutor.nav.today"), icon: Sun, count: waiting.toMark },
    {
      to: "/tutor/schedule",
      label: t("tutor.nav.schedule"),
      icon: CalendarDays,
      group: "teaching",
    },
    {
      to: "/tutor/students",
      label: t("tutor.nav.students"),
      icon: GraduationCap,
      group: "teaching",
    },
    {
      to: "/tutor/availability",
      label: t("tutor.nav.availability"),
      icon: Clock,
      group: "teaching",
    },
    {
      to: "/tutor/calendar",
      label: t("tutor.nav.calendar"),
      icon: CalendarSync,
      group: "teaching",
    },
    {
      to: "/tutor/jobs",
      label: t("tutor.nav.jobs"),
      icon: Briefcase,
      group: "teaching",
      count: waiting.offers,
    },
    {
      to: "/tutor/homework",
      label: t("learning.tutor.homework"),
      icon: NotebookPen,
      group: "teaching",
    },
    {
      to: "/tutor/resources",
      label: t("learning.tutor.resources"),
      icon: Library,
      group: "teaching",
    },
    ...(me.data.can_see_pay
      ? [{ to: "/tutor/earnings", label: t("tutor.nav.earnings"), icon: Wallet, group: "money" }]
      : []),
    { to: "/tutor/expenses", label: t("tutor.nav.expenses"), icon: ReceiptText, group: "money" },
    {
      to: "/tutor/invoice-review",
      label: t("g3.tutorReview.nav"),
      icon: FileCheck,
      group: "money",
    },
    {
      to: "/tutor/messages",
      label: t("portalMessages.nav"),
      icon: MessageSquare,
      group: "you",
      count: waiting.unreadMessages,
    },
    {
      to: "/tutor/notifications",
      label: t("tutor.nav.notifications"),
      icon: Bell,
      group: "you",
      count: waiting.notifications,
    },
    { to: "/tutor/onboarding", label: t("tutor.nav.onboarding"), icon: ListChecks, group: "you" },
    { to: "/tutor/compliance", label: t("tutor.nav.compliance"), icon: ShieldCheck, group: "you" },
    { to: "/tutor/tests", label: t("hiring.tests.nav"), icon: ClipboardCheck, group: "you" },
    { to: "/tutor/profile", label: t("tutor.nav.profile"), icon: UserRound, group: "you" },
    { to: "/tutor/referrals", label: t("referrals.tutorPortal.nav"), icon: Gift, group: "you" },
  ];
  return (
    <PortalFrame
      brand={<BrandMark fallback={organisation} />}
      navLabel={t("tutor.menu")}
      items={nav}
      primary={[
        "/tutor",
        "/tutor/schedule",
        "/tutor/students",
        "/tutor/earnings",
        "/tutor/messages",
      ]}
      groups={{
        teaching: t("portalFrame.groups.teaching"),
        money: t("portalFrame.groups.money"),
        you: t("portalFrame.groups.you"),
      }}
      root="/tutor"
      person={me.data.name}
      onSignOut={() => logout.mutate()}
      banner={<OfflineIndicator />}
      footer={<PoweredBy />}
    >
      <Outlet />
    </PortalFrame>
  );
}
