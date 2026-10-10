import { unwrap } from "@tutortrack/api-client";
import { useTranslation } from "@tutortrack/i18n";
import { Alert, Spinner } from "@tutortrack/ui";
import { useQuery } from "@tanstack/react-query";
import { Link, Outlet } from "@tanstack/react-router";
import { useEffect } from "react";

import { api, isAuthError } from "../api";

const NAV = [
  { to: "/platform", key: "platform.nav.tenants" },
  { to: "/platform/flags", key: "platform.nav.flags" },
  { to: "/platform/operations", key: "platform.nav.operations" },
] as const;

/** The TutorTrack staff console (E30): platform staff with 2FA, from allowed networks. */
export function PlatformShell() {
  const { t } = useTranslation();
  const me = useQuery({
    queryKey: ["platform", "me"],
    queryFn: async () => unwrap(await api.GET("/api/v1/platform/me")),
    retry: false,
  });
  const signedOut = me.isError && isAuthError(me.error);
  useEffect(() => {
    if (signedOut) window.location.assign("/login?next=%2Fplatform");
  }, [signedOut]);

  if (me.isPending || signedOut) {
    return (
      <div className="grid h-screen place-items-center">
        <Spinner className="size-6" label={t("grid.loading")} />
      </div>
    );
  }
  const access = me.data;
  const problem = !access?.is_platform_staff
    ? t("platform.notStaff")
    : !access.mfa_verified
      ? t("platform.needsMfa")
      : !access.network_allowed
        ? t("platform.wrongNetwork")
        : null;
  return (
    <div className="min-h-screen md:flex">
      <nav
        aria-label={t("platform.title")}
        className="border-b border-border p-4 md:w-56 md:border-b-0 md:border-r"
      >
        <p className="mb-3 font-semibold">{t("platform.title")}</p>
        <ul className="flex gap-2 md:flex-col">
          {NAV.map((item) => (
            <li key={item.to}>
              <Link
                to={item.to}
                activeOptions={{ exact: item.to === "/platform" }}
                className="block rounded-md px-2 py-1 hover:bg-muted [&.active]:font-medium"
              >
                {t(item.key)}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
      <main className="flex-1 p-4 md:p-8">
        {problem ? <Alert tone="danger">{problem}</Alert> : <Outlet />}
      </main>
    </div>
  );
}
