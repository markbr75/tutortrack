/**
 * Product tours for key flows (E30 FR-30-5). A step points at an element with a CSS
 * selector; when the element isn't on the page the step is shown without a highlight, so a
 * tour never blocks. Texts live in the `tours` i18n namespace (`tours.<tour>.<step>.*`).
 */
export interface TourStep {
  key: string;
  target?: string;
}

export interface TourDefinition {
  key: string;
  /** Where the tour starts (the help panel navigates there first). */
  path: string;
  steps: TourStep[];
}

export const TOURS: TourDefinition[] = [
  {
    key: "welcome",
    path: "/",
    steps: [
      { key: "intro" },
      { key: "navigation", target: "nav[aria-label='Main']" },
      { key: "checklist", target: "[data-tour='setup-checklist']" },
      { key: "help", target: "[data-tour='help']" },
    ],
  },
  {
    key: "calendar",
    path: "/calendar",
    steps: [
      { key: "intro", target: "main h1" },
      { key: "lessons", target: "main" },
      { key: "availability", target: "nav a[href='/availability']" },
    ],
  },
  {
    key: "billing",
    path: "/billing",
    steps: [
      { key: "intro", target: "main h1" },
      { key: "invoices", target: "main" },
      { key: "payments", target: "nav a[href='/settings/payments']" },
    ],
  },
];

export function tourByKey(key: string): TourDefinition | undefined {
  return TOURS.find((tour) => tour.key === key);
}
