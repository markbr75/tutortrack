import type { QueryClient } from "@tanstack/react-query";
import {
  createRootRouteWithContext,
  createRoute,
  createRouter,
  type RouterHistory,
} from "@tanstack/react-router";

import { BillingPage } from "./pages/BillingPage";
import { HomePage } from "./pages/HomePage";
import { ProfilePage } from "./pages/ProfilePage";
import { ReportsPage } from "./pages/ReportsPage";
import { SchedulePage } from "./pages/SchedulePage";
import { Shell } from "./Shell";
import { LessonPage } from "./tutor/LessonPage";
import { AvailabilityPage, StudentsPage, TutorProfilePage } from "./tutor/OtherPages";
import { JobsPage } from "./tutor/JobsPages";
import { ChecksPage, OnboardingPage } from "./tutor/OnboardingPages";
import { EarningsPage, ExpensesPage } from "./tutor/PayPages";
import { TutorReportPage } from "./tutor/ReportPage";
import { TutorSchedulePage } from "./tutor/SchedulePage";
import { TodayPage } from "./tutor/TodayPage";

const rootRoute = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  component: Shell,
});
const page = <P extends string>(path: P, component: () => JSX.Element | null) =>
  createRoute({ getParentRoute: () => rootRoute, path, component });

const lessonRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/tutor/lessons/$lessonId",
  component: function LessonRoute() {
    return <LessonPage lessonId={lessonRoute.useParams().lessonId} />;
  },
});
const reportRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/tutor/reports/$reportId",
  component: function ReportRoute() {
    return <TutorReportPage reportId={reportRoute.useParams().reportId} />;
  },
});

const routeTree = rootRoute.addChildren([
  page("/", HomePage),
  page("/schedule", SchedulePage),
  page("/reports", ReportsPage),
  page("/billing", BillingPage),
  page("/profile", ProfilePage),
  page("/tutor", TodayPage),
  page("/tutor/schedule", TutorSchedulePage),
  page("/tutor/students", StudentsPage),
  page("/tutor/availability", AvailabilityPage),
  page("/tutor/earnings", EarningsPage),
  page("/tutor/expenses", ExpensesPage),
  page("/tutor/onboarding", OnboardingPage),
  page("/tutor/compliance", ChecksPage),
  page("/tutor/jobs", JobsPage),
  page("/tutor/profile", TutorProfilePage),
  lessonRoute,
  reportRoute,
]);

export function createPortalRouter(queryClient: QueryClient, history?: RouterHistory) {
  return createRouter({ routeTree, context: { queryClient }, history, basepath: "/portal" });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof createPortalRouter>;
  }
}
