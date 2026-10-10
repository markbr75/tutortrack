import type { QueryClient } from "@tanstack/react-query";
import {
  createRootRouteWithContext,
  createRoute,
  createRouter,
  Outlet,
  type RouterHistory,
} from "@tanstack/react-router";

import { BillingPage } from "./billing/BillingPage";
import { InvoicePage } from "./billing/InvoicePage";
import { PayPage, SetupPage } from "./payments/PayPage";
import { PaymentsSettingsPage } from "./payments/PaymentsPages";
import { AvailabilityPage } from "./calendar/AvailabilityPage";
import { CalendarPage } from "./calendar/CalendarPage";
import { CataloguePage } from "./catalogue/CataloguePage";
import { IntegrationsPage } from "./integrations/IntegrationsPage";
import { NotificationSettingsPage } from "./comms/NotificationSettingsPage";
import { AnnouncementsPage } from "./portal/AnnouncementsPage";
import { TasksPage } from "./crm/TasksPage";
import { DeliverySettingsPage } from "./delivery/DeliverySettingsPage";
import { ReportPage } from "./delivery/ReportPage";
import { ReportsPage } from "./delivery/ReportsPage";
import { UnconfirmedPage } from "./delivery/UnconfirmedPage";
import { AutomationBuilderPage, AutomationsPage } from "./automations/AutomationPages";
import { JobPage } from "./jobs/JobPage";
import { JobMatchPage, MatchingPage } from "./matching/MatchingPages";
import { JobsPage } from "./jobs/JobsPage";
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
import { FlagsPage } from "./platform/FlagsPage";
import { OperationsPage } from "./platform/OperationsPage";
import { PlatformShell } from "./platform/PlatformShell";
import { TenantPage } from "./platform/TenantPage";
import { TenantsPage } from "./platform/TenantsPage";
import { ExpensesPage, PayItemsPage, PayRunPage, PayRunsPage } from "./payroll/PayrollPages";
import { BoardPage, EnquiryPage } from "./leads/LeadsPages";
import { FormsPage, FunnelPage, OfferPage, PublicFormPage, WaitlistPage } from "./leads/MorePages";
import {
  ApplicationPage,
  ApplicationsPage,
  ComplianceDashboardPage,
  InterviewChoicePage,
  ReferencePage,
  VacanciesPage,
  VacancyPage,
} from "./recruitment/RecruitmentPages";
import { PlanPage } from "./subscription/PlanPage";
import { TeamPage } from "./routes/TeamPage";
import { ReportsLibraryPage, ReportViewPage, SavedReportsPage } from "./reporting/ReportingPages";
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
const payRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/pay/$token",
  component: function PayRoute() {
    return <PayPage token={payRoute.useParams().token} />;
  },
});
const paySetupRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/pay/setup/$token",
  component: function PaySetupRoute() {
    return <SetupPage token={paySetupRoute.useParams().token} />;
  },
});

// Public enquiry forms and waitlist offers (E17).
const publicFormRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/f/$slug",
  component: function PublicFormRoute() {
    return <PublicFormPage slug={publicFormRoute.useParams().slug} />;
  },
});
const offerRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/offers/$token",
  component: function OfferRoute() {
    return <OfferPage token={offerRoute.useParams().token} />;
  },
});

// Tutor recruitment (E18): open roles, applications, interview times and references.
const vacanciesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/vacancies",
  component: VacanciesPage,
});
const vacancyRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/vacancies/$slug",
  component: function VacancyRoute() {
    return <VacancyPage slug={vacancyRoute.useParams().slug} />;
  },
});
const interviewRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/interviews/$token",
  component: function InterviewRoute() {
    return <InterviewChoicePage token={interviewRoute.useParams().token} />;
  },
});
const referenceRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/references/$token",
  component: function ReferenceRoute() {
    return <ReferencePage token={referenceRoute.useParams().token} />;
  },
});

// TutorTrack staff console (E30), outside the organisation's shell.
const platformRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/platform",
  component: PlatformShell,
});
const platformTenantsRoute = createRoute({
  getParentRoute: () => platformRoute,
  path: "/",
  component: TenantsPage,
});
const platformTenantRoute = createRoute({
  getParentRoute: () => platformRoute,
  path: "/tenants/$id",
  component: function PlatformTenantRoute() {
    return <TenantPage id={platformTenantRoute.useParams().id} />;
  },
});
const platformFlagsRoute = createRoute({
  getParentRoute: () => platformRoute,
  path: "/flags",
  component: FlagsPage,
});
const platformOpsRoute = createRoute({
  getParentRoute: () => platformRoute,
  path: "/operations",
  component: OperationsPage,
});

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
const jobsRoute = appPage("/jobs", JobsPage);
const calendarRoute = appPage("/calendar", CalendarPage);
const availabilityRoute = appPage("/availability", AvailabilityPage);
const reportsRoute = appPage("/reports", ReportsPage);
const reportRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/reports/$reportId",
  component: function ReportRoute() {
    return <ReportPage reportId={reportRoute.useParams().reportId} />;
  },
});
const analyticsRoute = appPage("/analytics", ReportsLibraryPage);
const analyticsSavedRoute = appPage("/analytics/saved", SavedReportsPage);
const analyticsReportRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/analytics/$key",
  component: function AnalyticsReportRoute() {
    return <ReportViewPage reportKey={analyticsReportRoute.useParams().key} />;
  },
});
const unconfirmedRoute = appPage("/unconfirmed", UnconfirmedPage);
const deliverySettingsRoute = appPage("/lesson-policies", DeliverySettingsPage);
const billingRoute = appPage("/billing", BillingPage);
const paymentsSettingsRoute = appPage("/settings/payments", PaymentsSettingsPage);
const notificationSettingsRoute = appPage("/settings/notifications", NotificationSettingsPage);
const planRoute = appPage("/settings/plan", PlanPage);
const integrationsRoute = appPage("/settings/integrations", IntegrationsPage);
const payRunsRoute = appPage("/payroll", PayRunsPage);
const payExpensesRoute = appPage("/payroll/expenses", ExpensesPage);
const payItemsRoute = appPage("/payroll/items", PayItemsPage);
const leadsRoute = appPage("/leads", BoardPage);
const leadsFormsRoute = appPage("/leads/forms", FormsPage);
const leadsWaitlistRoute = appPage("/leads/waitlist", WaitlistPage);
const leadsReportsRoute = appPage("/leads/reports", FunnelPage);
const enquiryRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/leads/$id",
  component: function EnquiryRoute() {
    return <EnquiryPage id={enquiryRoute.useParams().id} />;
  },
});
const recruitmentRoute = appPage("/recruitment", ApplicationsPage);
const complianceRoute = appPage("/compliance", ComplianceDashboardPage);
const matchingRoute = appPage("/matching", MatchingPage);
const automationsRoute = appPage("/automations", AutomationsPage);
const automationRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/automations/$id",
  component: function AutomationRoute() {
    return <AutomationBuilderPage id={automationRoute.useParams().id} />;
  },
});
const jobMatchRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/jobs/$jobId/match",
  component: function JobMatchRoute() {
    return <JobMatchPage jobId={jobMatchRoute.useParams().jobId} />;
  },
});
const applicationRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/recruitment/$id",
  component: function ApplicationRoute() {
    return <ApplicationPage id={applicationRoute.useParams().id} />;
  },
});
const payRunRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/payroll/runs/$id",
  component: function PayRunRoute() {
    return <PayRunPage id={payRunRoute.useParams().id} />;
  },
});
const announcementsRoute = appPage("/announcements", AnnouncementsPage);
const invoiceRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/invoices/$invoiceId",
  component: function InvoiceRoute() {
    return <InvoicePage invoiceId={invoiceRoute.useParams().invoiceId} />;
  },
});
const jobRoute = createRoute({
  getParentRoute: () => appRoute,
  path: "/jobs/$jobId",
  component: function JobRoute() {
    return <JobPage jobId={jobRoute.useParams().jobId} />;
  },
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
  payRoute,
  paySetupRoute,
  publicFormRoute,
  offerRoute,
  vacanciesRoute,
  vacancyRoute,
  interviewRoute,
  referenceRoute,
  platformRoute.addChildren([
    platformTenantsRoute,
    platformTenantRoute,
    platformFlagsRoute,
    platformOpsRoute,
  ]),
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
    jobsRoute,
    jobRoute,
    jobMatchRoute,
    matchingRoute,
    automationsRoute,
    automationRoute,
    calendarRoute,
    availabilityRoute,
    reportsRoute,
    reportRoute,
    analyticsRoute,
    analyticsSavedRoute,
    analyticsReportRoute,
    unconfirmedRoute,
    deliverySettingsRoute,
    billingRoute,
    invoiceRoute,
    paymentsSettingsRoute,
    notificationSettingsRoute,
    planRoute,
    integrationsRoute,
    payRunsRoute,
    payExpensesRoute,
    payItemsRoute,
    payRunRoute,
    recruitmentRoute,
    complianceRoute,
    applicationRoute,
    leadsRoute,
    leadsFormsRoute,
    leadsWaitlistRoute,
    leadsReportsRoute,
    enquiryRoute,
    announcementsRoute,
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
