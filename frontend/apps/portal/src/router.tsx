import type { QueryClient } from "@tanstack/react-query";
import {
  createRootRouteWithContext,
  createRoute,
  createRouter,
  type RouterHistory,
} from "@tanstack/react-router";

import {
  AffiliateClientsPage,
  AffiliateHomePage,
  AffiliatePayoutPage,
  AffiliateStatementsPage,
} from "./affiliate/AffiliatePages";
import { ClassroomPage, RecordingsPage } from "./classroom/ClassroomPage";
import { BillingPage } from "./pages/BillingPage";
import { BookingPage } from "./pages/BookingPage";
import { ClassesPage } from "./pages/ClassesPage";
import { DocumentsPage } from "./pages/DocumentsPage";
import { FamilyPage } from "./pages/FamilyPage";
import { HomePage } from "./pages/HomePage";
import { HomeworkPage, LearningPage } from "./pages/LearningPage";
import { MessagesPage, TutorMessagesPage } from "./pages/MessagesPage";
import { PrivacyPage } from "./pages/PrivacyPage";
import { ProfilePage } from "./pages/ProfilePage";
import { ReferralsPage } from "./pages/ReferralsPage";
import { ReportsPage } from "./pages/ReportsPage";
import { SchedulePage } from "./pages/SchedulePage";
import { Shell } from "./Shell";
import { LessonPage } from "./tutor/LessonPage";
import { CalendarSyncPage } from "./tutor/CalendarSyncPage";
import { AvailabilityPage, StudentsPage, TutorProfilePage } from "./tutor/OtherPages";
import { JobsPage } from "./tutor/JobsPages";
import { ChecksPage, OnboardingPage } from "./tutor/OnboardingPages";
import { NotificationsPage } from "./push/NotificationsPage";
import { OfflineReportPage } from "./tutor/OfflineReportPage";
import { EarningsPage, ExpensesPage } from "./tutor/PayPages";
import { TutorReferralsPage } from "./tutor/ReferralsPage";
import { TutorReportPage } from "./tutor/ReportPage";
import { TutorSchedulePage } from "./tutor/SchedulePage";
import { TodayPage } from "./tutor/TodayPage";
import { TutorHomeworkPage, TutorResourcesPage, TutorReviewPage } from "./tutor/LearningPages";

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
const offlineReportRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/tutor/lessons/$lessonId/report",
  component: function OfflineReportRoute() {
    return <OfflineReportPage lessonId={offlineReportRoute.useParams().lessonId} />;
  },
});
const reportRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/tutor/reports/$reportId",
  component: function ReportRoute() {
    return <TutorReportPage reportId={reportRoute.useParams().reportId} />;
  },
});
const homeworkRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/learning/homework/$assignmentId",
  component: function HomeworkRoute() {
    return <HomeworkPage assignmentId={homeworkRoute.useParams().assignmentId} />;
  },
});
const tutorReviewRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/tutor/homework/$assignmentId",
  component: function TutorReviewRoute() {
    return <TutorReviewPage assignmentId={tutorReviewRoute.useParams().assignmentId} />;
  },
});

const classroomRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/classroom/$lessonId",
  component: function ClassroomRoute() {
    return <ClassroomPage lessonId={classroomRoute.useParams().lessonId} />;
  },
});

const routeTree = rootRoute.addChildren([
  page("/", HomePage),
  page("/schedule", SchedulePage),
  page("/book", BookingPage),
  page("/classes", ClassesPage),
  page("/reports", ReportsPage),
  page("/billing", BillingPage),
  page("/profile", ProfilePage),
  page("/family", FamilyPage),
  page("/documents", DocumentsPage),
  page("/privacy", PrivacyPage),
  page("/referrals", ReferralsPage),
  page("/messages", MessagesPage),
  page("/affiliate", AffiliateHomePage),
  page("/affiliate/clients", AffiliateClientsPage),
  page("/affiliate/statements", AffiliateStatementsPage),
  page("/affiliate/payout", AffiliatePayoutPage),
  page("/tutor", TodayPage),
  page("/tutor/schedule", TutorSchedulePage),
  page("/tutor/students", StudentsPage),
  page("/tutor/availability", AvailabilityPage),
  page("/tutor/calendar", CalendarSyncPage),
  page("/tutor/earnings", EarningsPage),
  page("/tutor/expenses", ExpensesPage),
  page("/tutor/onboarding", OnboardingPage),
  page("/tutor/compliance", ChecksPage),
  page("/tutor/jobs", JobsPage),
  page("/tutor/profile", TutorProfilePage),
  page("/tutor/notifications", NotificationsPage),
  page("/tutor/referrals", TutorReferralsPage),
  page("/learning", LearningPage),
  homeworkRoute,
  page("/tutor/homework", TutorHomeworkPage),
  tutorReviewRoute,
  page("/tutor/resources", TutorResourcesPage),
  page("/tutor/messages", TutorMessagesPage),
  lessonRoute,
  classroomRoute,
  page("/recordings", RecordingsPage),
  offlineReportRoute,
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
