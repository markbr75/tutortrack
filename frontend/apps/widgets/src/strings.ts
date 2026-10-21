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
  attachOnFullForm: "To attach files, use our full form (opens in a new tab)",
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
  bookingService: "What would you like to book?",
  bookingChoose: "Choose a lesson",
  bookingTimes: "Choose a time",
  bookingNoTimes: "No free times in the next few days. Please try again later or contact us.",
  bookingFirstName: "Your first name",
  bookingLastName: "Your last name",
  bookingEmail: "Email",
  bookingPhone: "Phone (optional)",
  bookingStudent: "Student's first name",
  bookingPromo: "Promo code (optional)",
  bookingContinue: "Continue",
  bookingHeld: "We're holding this time for you until {time}.",
  bookingBook: "Book now",
  bookingConfirmed: "You're booked. We've sent you the details.",
  bookingRequested: "Thanks! We'll confirm your booking soon.",
  bookingPay: "Please pay to confirm your booking.",
  bookingPayNow: "Pay now",
  bookingTaken:
    "Sorry, that time has just been taken, or the code isn't valid. Please check and try again.",
  bookingExpired: "The time we held has run out. Please choose again.",
  classesTitle: "Classes",
  classesNone: "No classes are open for enrolment at the moment.",
  classesAge: "Child's age",
  classesDay: "Day",
  classesAnyDay: "Any day",
  classesFull: "Full",
  classesPlacesLeft: "{n} places left",
  classesEnrol: "Enrol",
  classesEnrolIn: "Enrol in {name}",
  classesJoinWaitlist: "Join the waitlist",
  classesJoinWaitlistFor: "Join the waitlist for {name}",
  classesBirthday: "Child's date of birth",
  classesYearGroup: "School year",
  classesTerms: "Terms",
  classesAccept: "I accept the terms",
  classesPhotoConsent: "You may use photos and video of my child",
  classesNewsConsent: "Send me news and offers by email",
  classesBack: "Back to classes",
  classesEnrolled: "{name} is enrolled. We've sent you the details.",
  classesWaitlisted: "You're on the waitlist (number {n}). We'll email you if a place comes up.",
};

export type MessageKey = keyof typeof enGB;
type Messages = Record<MessageKey, string>;

const overrides: Record<string, Partial<Messages>> = {
  "en-US": {
    classesNone: "No classes are open for enrollment at the moment.",
    classesEnrol: "Enroll",
    classesEnrolIn: "Enroll in {name}",
    classesYearGroup: "Grade",
  },
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
