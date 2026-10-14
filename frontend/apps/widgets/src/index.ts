/**
 * Widget runtime entry (E24 FR-24-3). One script, every widget:
 *
 *   <script type="module" src="https://cdn.tutortrack.app/widgets.js" data-org="slug"></script>
 *   <tt-tutor-directory widget="w-..."></tt-tutor-directory>
 *
 * Each widget is a Lit custom element with Shadow DOM isolation, themed by the organisation's
 * brand and CSS custom properties (`--tt-brand-color`, `--tt-font`, `--tt-radius`...), and
 * emits `tt:*` analytics events on window. Self-booking is `<tt-booking>` (E08-T14); the course
 * catalogue with online enrolment is `<tt-class-catalogue>` (E20).
 */
export { TtBooking } from "./booking";
export { TtClassCatalogue } from "./class-catalogue";
export { TtCookieConsent } from "./cookie-consent";
export { TtEnquiryForm } from "./enquiry-form";
export { TtJobOpenings } from "./job-openings";
export { TtLogin } from "./login";
export { TtPoweredBy } from "./powered-by";
export { TtReviews } from "./reviews";
export { TtServices } from "./services";
export { TtTutorDirectory } from "./tutor-directory";
export { applyTheme, emit } from "./runtime";
export { captureReferral, referralCode } from "./referral";

import { captureReferral } from "./referral";

// E25: a visit through a referral or affiliate link (?ref=CODE) is counted and remembered.
void captureReferral();
