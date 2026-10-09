import { useTranslation } from "@tutortrack/i18n";
import { Spinner } from "@tutortrack/ui";
import { useMutation } from "@tanstack/react-query";
import { Link, Outlet, useLocation, useNavigate } from "@tanstack/react-router";
import { useEffect } from "react";

import { api } from "../api";
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
  const logout = useMutation({
    mutationFn: async () => api.POST("/api/v1/auth/logout"),
    onSuccess: () => window.location.assign("/portal/"),
  });
  if (me.isPending) return <Spinner className="m-8 size-6" label={t("grid.loading")} />;
  if (!me.data) return <p className="p-6">{t("tutor.noProfile")}</p>;
  const nav = [
    { to: "/tutor", label: t("tutor.nav.today") },
    { to: "/tutor/schedule", label: t("tutor.nav.schedule") },
    { to: "/tutor/students", label: t("tutor.nav.students") },
    { to: "/tutor/availability", label: t("tutor.nav.availability") },
    ...(me.data.can_see_pay ? [{ to: "/tutor/earnings", label: t("tutor.nav.earnings") }] : []),
    { to: "/tutor/profile", label: t("tutor.nav.profile") },
  ] as const;
  return (
    <div className="mx-auto min-h-screen max-w-3xl">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-border p-4">
        <span className="font-semibold">{me.data.name}</span>
        <nav aria-label={t("tutor.menu")} className="flex flex-wrap gap-1 text-sm">
          {nav.map((item) => (
            <Link
              key={item.to}
              to={item.to}
              className="rounded-md px-3 py-2 hover:bg-muted"
              activeProps={{ className: "bg-muted font-medium" }}
              activeOptions={{ exact: item.to === "/tutor" }}
            >
              {item.label}
            </Link>
          ))}
          <button
            type="button"
            className="rounded-md px-3 py-2 hover:bg-muted"
            onClick={() => logout.mutate()}
          >
            {t("portal.signOut")}
          </button>
        </nav>
      </header>
      <main className="p-4">
        <Outlet />
      </main>
    </div>
  );
}
