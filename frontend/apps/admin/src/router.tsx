import type { QueryClient } from "@tanstack/react-query";
import {
  createRootRouteWithContext,
  createRoute,
  createRouter,
  Outlet,
  type RouterHistory,
} from "@tanstack/react-router";

import { CataloguePage } from "./catalogue/CataloguePage";
import { TasksPage } from "./crm/TasksPage";
import { AppShell } from "./layout/AppShell";
import { ClientsPage, StudentsPage, TutorsPage } from "./people/PeopleLists";
import { QuickAddFamilyPage } from "./people/QuickAddFamilyPage";
import { ClientPage, StudentPage, TutorPage } from "./people/RecordPages";
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

const publicPage = <P extends string>(path: P, component: () => JSX.Element) =>
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

const appPage = <P extends string>(path: P, component: () => JSX.Element) =>
  createRoute({ getParentRoute: () => appRoute, path, component });
const clientsRoute = appPage("/clients", ClientsPage);
const quickAddRoute = appPage("/clients/new", QuickAddFamilyPage);
const clientRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/clients/$clientId",
  component: function ClientRoute() {
    return <ClientPage clientId={clientRoute.useParams().clientId} />;
  },
});
const studentsRoute = appPage("/students", StudentsPage);
const studentRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/students/$studentId",
  component: function StudentRoute() {
    return <StudentPage studentId={studentRoute.useParams().studentId} />;
  },
});
const tutorsRoute = appPage("/tutors", TutorsPage);
const tutorRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/tutors/$tutorId",
  component: function TutorRoute() {
    return <TutorPage tutorId={tutorRoute.useParams().tutorId} />;
  },
});
const tasksRoute = appPage("/tasks", TasksPage);
const catalogueRoute = appPage("/catalogue", CataloguePage);

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
  appRoute.addChildren([
    homeRoute,
    clientsRoute,
    quickAddRoute,
    clientRoute,
    studentsRoute,
    studentRoute,
    tutorsRoute,
    tutorRoute,
    tasksRoute,
    catalogueRoute,
    teamRoute,
    auditRoute,
    settingsRoute,
    accountRoute,
  ]),
]);

export function createAppRouter(queryClient: QueryClient, history?: RouterHistory) {
  return createRouter({ routeTree, context: { queryClient }, history });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof createAppRouter>;
  }
}
