import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Button, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Outlet, useLocation, useNavigate } from "@tanstack/react-router";
import {
  BookOpen,
  CalendarDays,
  CalendarPlus,
  CreditCard,
  FilePen,
  FileText,
  Gift,
  House,
  MessageSquare,
  ShieldCheck,
  UserRound,
  Users,
  UsersRound,
  Video,
} from "lucide-react";
import { useEffect, useState } from "react";

import { api, isSignedOut, problemStatus, usePortalMe } from "./api";
import { BrandMark, PoweredBy } from "./branding";
import { OfflineBanner } from "./offline/OfflineIndicator";
import { HouseholdSwitcher, StudentSignIn } from "./HouseholdSwitcher";
import { PortalFrame } from "./layout/PortalFrame";
import { isPositive } from "./money";
import { StatusBanner } from "./StatusBanner";
import { usePortalBranding } from "./useBranding";
import { AffiliateShell } from "./affiliate/AffiliatePages";
import { TutorShell } from "./tutor/TutorShell";

export function SignIn() {
  const { t } = useTranslation();
  const brand = usePortalBranding();
  const [email, setEmail] = useState("");
  const send = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/v1/auth/magic-link", { body: { email, next: "/portal/" } })),
  });
  return (
    <main className="mx-auto flex min-h-dvh max-w-sm flex-col justify-center gap-6 px-4 py-10">
      <div className="text-center">{brand ? <BrandMark fallback={brand.name} /> : null}</div>
      <section
        aria-labelledby="sign-in-h"
        className="space-y-4 rounded-xl border border-border bg-surface p-5"
      >
        <h1 id="sign-in-h" className="text-xl font-semibold">
          {t("portal.signIn")}
        </h1>
        {send.isSuccess ? (
          <p role="status">{t("portal.checkEmail", { email })}</p>
        ) : (
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              send.mutate();
            }}
          >
            <TextField
              type="email"
              required
              autoComplete="email"
              label={t("portal.email")}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <Button type="submit" className="w-full" disabled={send.isPending}>
              {t("portal.sendLink")}
            </Button>
          </form>
        )}
      </section>
      <section className="border-t border-border pt-5">
        <StudentSignIn />
      </section>
      <PoweredBy />
    </main>
  );
}

/** Signed in as a tutor, or as staff who teach → the tutor shell (E16); otherwise the family
 * shell (E15). */
export function Shell() {
  const { t } = useTranslation();
  const who = useQuery({
    queryKey: ["identity", "me"],
    queryFn: async () => unwrap(await api.GET("/api/v1/me")),
  });
  usePortalBranding();
  if (who.isPending) return <Spinner className="p-6" label={t("grid.loading")} />;
  if (isSignedOut(who.error)) return <SignIn />;
  return (
    <>
      <StatusBanner />
      {/* Tutors, and people who run the business and teach too (a sole trader, say). */}
      {who.data?.membership?.role === "tutor" || who.data?.membership?.teaches ? (
        <TutorShell />
      ) : who.data?.membership?.role === "affiliate" ? (
        <AffiliateShell />
      ) : (
        <>
          <OfflineBanner />
          <FamilyShell person={personName(who.data?.user)} />
        </>
      )}
    </>
  );
}

function personName(
  user: { first_name?: string; last_name?: string; email?: string } | null | undefined,
): string {
  return [user?.first_name, user?.last_name].filter(Boolean).join(" ") || user?.email || "";
}

/** What waits for the family, for the tab bar's count pills: unread messages and invoices
 * past their due date (both from data the screens already load, so the caches are shared). */
function useFamilyWaiting(features: { messages?: boolean; invoices?: boolean } | undefined) {
  const threads = useQuery({
    queryKey: ["portal", "threads", "family"],
    enabled: Boolean(features?.messages),
    refetchInterval: 60_000,
    queryFn: async () => unwrap(await api.GET("/api/v1/portal/threads")),
  });
  const billing = useQuery({
    queryKey: ["portal", "billing"],
    enabled: Boolean(features?.invoices),
    queryFn: async () => unwrap(await api.GET("/api/v1/portal/billing")),
  });
  const today = new Date().toISOString().slice(0, 10);
  return {
    unread: (threads.data ?? []).reduce((sum, row) => sum + (row.unread ?? 0), 0),
    overdue: (billing.data?.invoices ?? []).filter(
      (inv) => isPositive(inv.balance_due.amount) && Boolean(inv.due_date) && inv.due_date! < today,
    ).length,
  };
}

function FamilyShell({ person }: { person: string }) {
  const { t } = useTranslation();
  const me = usePortalMe();
  const location = useLocation();
  const navigate = useNavigate();
  useEffect(() => {
    if (location.pathname.startsWith("/tutor") || location.pathname.startsWith("/affiliate")) {
      void navigate({ to: "/" });
    }
  }, [location.pathname, navigate]);
  const logout = useMutation({
    mutationFn: async () => api.POST("/api/v1/auth/logout"),
    onSuccess: () => window.location.assign("/portal/"),
  });
  const waiting = useFamilyWaiting(me.data?.features);
  if (me.isPending) return <Spinner className="p-6" label={t("grid.loading")} />;
  if (isSignedOut(me.error)) return <SignIn />;
  const status = problemStatus(me.error);
  if (!me.data) {
    return (
      <main className="mx-auto max-w-sm space-y-3 p-6">
        <p>{t(status === 403 ? "portal.notFamily" : "errors.generic")}</p>
        <a className="font-medium text-link underline-offset-2 hover:underline" href="/">
          {t("portal.toMainApp")}
        </a>
      </main>
    );
  }
  const f = me.data.features;
  const nav = [
    { to: "/", label: t("portal.nav.home"), icon: House },
    { to: "/schedule", label: t("portal.nav.schedule"), icon: CalendarDays, group: "lessons" },
    ...(f.booking
      ? [{ to: "/book", label: t("portalBooking.nav"), icon: CalendarPlus, group: "lessons" }]
      : []),
    ...(f.classes
      ? [{ to: "/classes", label: t("portalCourses.nav"), icon: Users, group: "lessons" }]
      : []),
    ...(f.reports
      ? [{ to: "/reports", label: t("portal.nav.reports"), icon: FileText, group: "lessons" }]
      : []),
    ...(f.learning
      ? [{ to: "/learning", label: t("learning.portal.nav"), icon: BookOpen, group: "lessons" }]
      : []),
    { to: "/recordings", label: t("classroom.recordingsNav"), icon: Video, group: "lessons" },
    ...(f.invoices
      ? [
          {
            to: "/billing",
            label: t("portal.nav.billing"),
            icon: CreditCard,
            group: "account",
            count: waiting.overdue,
          },
        ]
      : []),
    ...(f.messages
      ? [
          {
            to: "/messages",
            label: t("portalMessages.nav"),
            icon: MessageSquare,
            group: "account",
            count: waiting.unread,
          },
        ]
      : []),
    ...(f.profile
      ? [{ to: "/profile", label: t("portal.nav.profile"), icon: UserRound, group: "account" }]
      : []),
    ...(f.guardian_invites || f.student_logins
      ? [{ to: "/family", label: t("family.nav"), icon: UsersRound, group: "account" }]
      : []),
    ...(f.documents
      ? [{ to: "/documents", label: t("esign.nav"), icon: FilePen, group: "account" }]
      : []),
    ...(f.referrals
      ? [{ to: "/referrals", label: t("referrals.portal.nav"), icon: Gift, group: "account" }]
      : []),
    { to: "/privacy", label: t("privacyCentre.portal.nav"), icon: ShieldCheck, group: "account" },
  ];
  return (
    <PortalFrame
      brand={<BrandMark fallback={me.data.organisation.name} />}
      navLabel={t("portal.menu")}
      items={nav}
      primary={["/", "/schedule", "/billing", "/messages", "/learning", "/reports"]}
      groups={{
        lessons: t("portalFrame.groups.lessons"),
        account: t("portalFrame.groups.account"),
      }}
      root="/"
      person={person}
      onSignOut={() => logout.mutate()}
      headerExtra={<HouseholdSwitcher me={me.data} />}
      footer={
        <>
          {me.data.help_url || me.data.terms_url ? (
            <p className="flex justify-center gap-4 px-4 pt-2 text-xs text-muted-foreground">
              {me.data.help_url ? <a href={me.data.help_url}>{t("portal.help")}</a> : null}
              {me.data.terms_url ? <a href={me.data.terms_url}>{t("portal.terms")}</a> : null}
            </p>
          ) : null}
          <PoweredBy />
        </>
      }
    >
      <Outlet />
    </PortalFrame>
  );
}
