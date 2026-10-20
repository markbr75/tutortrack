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
  UserRound,
  Wallet,
} from "lucide-react";
import { useEffect } from "react";

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

/** The tutor's phone-first shell (E16-T01). */
export function TutorShell() {
  const { t } = useTranslation();
  const me = useTutorMe();
  const location = useLocation();
  const navigate = useNavigate();
  useEffect(() => {
    if (!location.pathname.startsWith("/tutor")) void navigate({ to: "/tutor" });
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
  if (me.isPending) return <Spinner className="p-6" label={t("grid.loading")} />;
  if (!me.data) return <p className="p-6">{t("tutor.noProfile")}</p>;
  const nav = [
    { to: "/tutor", label: t("tutor.nav.today"), icon: Sun },
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
    { to: "/tutor/jobs", label: t("tutor.nav.jobs"), icon: Briefcase, group: "teaching" },
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
    { to: "/tutor/messages", label: t("portalMessages.nav"), icon: MessageSquare, group: "you" },
    { to: "/tutor/notifications", label: t("tutor.nav.notifications"), icon: Bell, group: "you" },
    { to: "/tutor/onboarding", label: t("tutor.nav.onboarding"), icon: ListChecks, group: "you" },
    { to: "/tutor/compliance", label: t("tutor.nav.compliance"), icon: ShieldCheck, group: "you" },
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
