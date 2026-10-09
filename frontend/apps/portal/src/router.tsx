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

const rootRoute = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  component: Shell,
});
const page = <P extends string>(path: P, component: () => JSX.Element | null) =>
  createRoute({ getParentRoute: () => rootRoute, path, component });

const routeTree = rootRoute.addChildren([
  page("/", HomePage),
  page("/schedule", SchedulePage),
  page("/reports", ReportsPage),
  page("/billing", BillingPage),
  page("/profile", ProfilePage),
]);

export function createPortalRouter(queryClient: QueryClient, history?: RouterHistory) {
  return createRouter({ routeTree, context: { queryClient }, history, basepath: "/portal" });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof createPortalRouter>;
  }
}
