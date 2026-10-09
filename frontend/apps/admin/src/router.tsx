import type { QueryClient } from "@tanstack/react-query";
import {
  createRootRouteWithContext,
  createRoute,
  createRouter,
  Outlet,
  type RouterHistory,
} from "@tanstack/react-router";

import { AppShell } from "./layout/AppShell";
import { AcceptInvitePage } from "./routes/AcceptInvitePage";
import { AccountPage } from "./routes/AccountPage";
import { AuditPage } from "./routes/AuditPage";
import { HomePage } from "./routes/HomePage";
import {
  ContinuePage,
  ForgotPasswordPage,
  LoginPage,
  MagicLinkPage,
  ResetPasswordPage,
} from "./routes/LoginPage";
import { NotFoundPage } from "./routes/NotFoundPage";
import { OnboardingPage } from "./routes/OnboardingPage";
import { SettingsPage } from "./routes/SettingsPage";
import { SignupPage } from "./routes/SignupPage";
import { TeamPage } from "./routes/TeamPage";
import { VerifyEmailPage } from "./routes/VerifyEmailPage";

interface RouterContext {
  queryClient: QueryClient;
}

const rootRoute = createRootRouteWithContext<RouterContext>()({
  component: Outlet,
  notFoundComponent: NotFoundPage,
});

// Public pages (no signed-in shell).
const signupRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/signup",
  component: SignupPage,
});
const verifyEmailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/verify-email",
  component: VerifyEmailPage,
});
// Onboarding signs in with the handoff token itself, so it sits outside the shell too.
const onboardingRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/onboarding",
  component: OnboardingPage,
});

const publicPage = (path: string, component: () => JSX.Element) =>
  createRoute({ getParentRoute: () => rootRoute, path, component });
const loginRoute = publicPage("/login", LoginPage);
const magicLinkRoute = publicPage("/login/magic", MagicLinkPage);
const forgotRoute = publicPage("/forgot-password", ForgotPasswordPage);
const resetRoute = publicPage("/reset-password", ResetPasswordPage);
const continueRoute = publicPage("/auth/continue", ContinuePage);
const acceptInviteRoute = publicPage("/accept-invite", AcceptInvitePage);

// Signed-in app.
const appRoute = createRoute({ getParentRoute: () => rootRoute, id: "app", component: AppShell });
const homeRoute = createRoute({ getParentRoute: () => appRoute, path: "/", component: HomePage });
const auditRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/audit",
  component: AuditPage,
});
const teamRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/team",
  component: TeamPage,
});
const accountRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/account",
  component: AccountPage,
});
const settingsRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/settings",
  component: SettingsPage,
});

const routeTree = rootRoute.addChildren([
  signupRoute,
  verifyEmailRoute,
  onboardingRoute,
  loginRoute,
  magicLinkRoute,
  forgotRoute,
  resetRoute,
  continueRoute,
  acceptInviteRoute,
  appRoute.addChildren([homeRoute, teamRoute, auditRoute, settingsRoute, accountRoute]),
]);

export function createAppRouter(queryClient: QueryClient, history?: RouterHistory) {
  return createRouter({ routeTree, context: { queryClient }, history });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof createAppRouter>;
  }
}
