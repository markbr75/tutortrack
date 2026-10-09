import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Button, Spinner, TextField } from "@tutortrack/ui";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, Outlet, useLocation, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";

import { api, problemStatus, usePortalMe } from "./api";
import { TutorShell } from "./tutor/TutorShell";

export function SignIn() {
  const { t } = useTranslation();
  const [email, setEmail] = useState("");
  const send = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST("/api/v1/auth/magic-link", { body: { email, next: "/portal/" } })),
  });
  return (
    <main className="mx-auto max-w-sm space-y-4 p-6">
      <h1 className="text-2xl font-semibold">{t("portal.signIn")}</h1>
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
          <Button type="submit" disabled={send.isPending}>
            {t("portal.sendLink")}
          </Button>
        </form>
      )}
    </main>
  );
}

/** Signed in as a tutor → the tutor shell (E16); otherwise the family shell (E15). */
export function Shell() {
  const { t } = useTranslation();
  const who = useQuery({
    queryKey: ["identity", "me"],
    queryFn: async () => unwrap(await api.GET("/api/v1/me")),
  });
  if (who.isPending) return <Spinner className="m-8 size-6" label={t("grid.loading")} />;
  if (problemStatus(who.error) === 401) return <SignIn />;
  if (who.data?.membership?.role === "tutor") return <TutorShell />;
  return <FamilyShell />;
}

function FamilyShell() {
  const { t } = useTranslation();
  const me = usePortalMe();
  const location = useLocation();
  const navigate = useNavigate();
  useEffect(() => {
    if (location.pathname.startsWith("/tutor")) void navigate({ to: "/" });
  }, [location.pathname, navigate]);
  const logout = useMutation({
    mutationFn: async () => api.POST("/api/v1/auth/logout"),
    onSuccess: () => window.location.assign("/portal/"),
  });
  if (me.isPending) return <Spinner className="m-8 size-6" label={t("grid.loading")} />;
  const status = problemStatus(me.error);
  if (status === 401) return <SignIn />;
  if (!me.data) {
    return (
      <main className="mx-auto max-w-sm space-y-3 p-6">
        <p>{t(status === 403 ? "portal.notFamily" : "errors.generic")}</p>
        <a className="underline" href="/">
          {t("portal.toMainApp")}
        </a>
      </main>
    );
  }
  const f = me.data.features;
  const nav = [
    { to: "/", label: t("portal.nav.home") },
    { to: "/schedule", label: t("portal.nav.schedule") },
    ...(f.reports ? [{ to: "/reports", label: t("portal.nav.reports") }] : []),
    ...(f.invoices ? [{ to: "/billing", label: t("portal.nav.billing") }] : []),
    ...(f.profile ? [{ to: "/profile", label: t("portal.nav.profile") }] : []),
  ] as const;
  return (
    <div className="mx-auto min-h-screen max-w-3xl">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-border p-4">
        <span
          className="font-semibold"
          style={
            me.data.organisation.primary_colour
              ? { color: me.data.organisation.primary_colour }
              : undefined
          }
        >
          {me.data.organisation.name}
        </span>
        <nav aria-label={t("portal.menu")} className="flex flex-wrap gap-1 text-sm">
          {nav.map((item) => (
            <Link
              key={item.to}
              to={item.to}
              className="rounded-md px-2 py-1 hover:bg-muted"
              activeProps={{ className: "bg-muted font-medium" }}
              activeOptions={{ exact: item.to === "/" }}
            >
              {item.label}
            </Link>
          ))}
          <button
            type="button"
            className="rounded-md px-2 py-1 hover:bg-muted"
            onClick={() => logout.mutate()}
          >
            {t("portal.signOut")}
          </button>
        </nav>
      </header>
      <main className="p-4">
        <Outlet />
      </main>
      {me.data.help_url || me.data.terms_url ? (
        <footer className="flex gap-4 p-4 text-xs text-muted-foreground">
          {me.data.help_url ? <a href={me.data.help_url}>{t("portal.help")}</a> : null}
          {me.data.terms_url ? <a href={me.data.terms_url}>{t("portal.terms")}</a> : null}
        </footer>
      ) : null}
    </div>
  );
}
