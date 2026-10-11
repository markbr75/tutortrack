/**
 * Widget text (i18n): en-GB defaults with per-locale overrides. Widgets pick the locale from
 * the script tag's `data-locale` (or the page's `lang`), and every string can also be
 * replaced by the host page through `window.TutorTrackWidgets.messages`.
 */
const enGB = {
  loading: "Loading…",
  error: "Sorry, this couldn't be loaded. Please try again later.",
  poweredBy: "Powered by",
  search: "Search tutors",
  subject: "Subject",
  anySubject: "Any subject",
  online: "Online",
  inPerson: "In person",
  anyMode: "Online or in person",
  howTaught: "Lessons",
  noTutors: "No tutors match your search.",
  results: "{n} tutors",
  more: "Show more",
  viewProfile: "View profile of {name}",
  back: "Back to all tutors",
  about: "About",
  subjects: "Subjects",
  qualifications: "Qualifications",
  languages: "Languages",
  experience: "{n} years of experience",
  enquire: "Enquire about {name}",
  send: "Send",
  sending: "Sending…",
  thanks: "Thank you. We'll be in touch soon.",
  required: "Required",
  fixErrors: "Please check the highlighted answers.",
  student: "Student {n} first name",
  studentSubjects: "Student {n} subjects",
  addStudent: "Add another student",
  website: "Website",
  price: "Price",
  askPrice: "Ask us",
  minutes: "{n} minutes",
  noServices: "No services listed yet.",
  stars: "{n} out of 5 stars",
  noReviews: "No reviews yet.",
  signIn: "Sign in",
  portalClient: "Parent and student login",
  portalTutor: "Tutor login",
  portalStaff: "Staff login",
  vacancies: "Tutor vacancies",
  apply: "Apply for {title}",
  noVacancies: "No vacancies right now.",
  closes: "Closes {date}",
};

export type MessageKey = keyof typeof enGB;
type Messages = Record<MessageKey, string>;

const overrides: Record<string, Partial<Messages>> = {
  "en-US": {},
};

declare global {
  interface Window {
    TutorTrackWidgets?: { messages?: Partial<Messages>; locale?: string };
  }
}

export function locale(): string {
  return (
    window.TutorTrackWidgets?.locale ||
    document.querySelector<HTMLScriptElement>("script[data-org]")?.dataset.locale ||
    document.documentElement.lang ||
    "en-GB"
  );
}

export function t(key: MessageKey, vars: Record<string, string | number> = {}): string {
  const text = window.TutorTrackWidgets?.messages?.[key] ?? overrides[locale()]?.[key] ?? enGB[key];
  return text.replace(/\{(\w+)\}/g, (_, name: string) => String(vars[name] ?? ""));
}
