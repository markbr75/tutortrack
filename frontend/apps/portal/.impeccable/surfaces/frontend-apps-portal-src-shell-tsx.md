---
version: 1
slug: "frontend-apps-portal-src-shell-tsx"
primary_target: "frontend/apps/portal/src/Shell.tsx"
related_targets: ["frontend/apps/portal/src/tutor/TutorShell.tsx","frontend/apps/portal/src/affiliate/AffiliatePages.tsx","frontend/apps/portal/src/pages/HomePage.tsx","frontend/apps/portal/src/tutor/TodayPage.tsx"]
---

# Portal shells (stage 4)

Scope: the portal's four role shells (family/student, tutor, affiliate) and each role's home screen (family/student Home, tutor Today, affiliate Overview), plus sign-in. Mode: Operate. Phone first (390px), also desktop.

Audience and job: parents check the next lesson, pay, message, move or cancel; students see lessons and learning; tutors run their day (join, mark, write reports); affiliates check referrals and copy their link. Visits are brief and one-handed.

Constraints: white-label (tenant logo/name, brand colour only on primary fills and the selected tab's tint); The Register world from DESIGN.md is fixed; nav lists stay in Shell.tsx, TutorShell.tsx and AffiliatePages.tsx (`{ to, label` pattern read by `manage.py guides --check`); feature-gated items stay gated; offline and household switching keep working.

Owner decisions (2026-10-20): bottom tab bar; shells and home screens; quiet branding.

## Direction contract

THESIS: The portal is a pocket register: one column where the next lesson and today's lessons read as ruled register rows with their marks, and four everyday destinations sit under the thumb. It refuses the wrapped cloud of seventeen links and the dashboard of number tiles.

OWN-WORLD: The Register: register-stock ground, clean-leaf panels with 1px register-blue rules and 12px corners, blue-black ink, Source Sans 3 in five sizes, authored register marks, the red margin rule only for now and what is owed or waiting. The tenant appears as logo or name in ink and as a soft brand tint behind the selected tab's icon and on primary button fills.

STORY: A parent opens the app and knows at once when the next lesson is, with whom and where, and can join, move or pay without hunting. A tutor sees today's register and what is waiting, then marks lessons. Everyone else is one tap on More away.

FIRST VIEWPORT: Phone: a 56px clean-leaf header (logo or business name left, household switcher and account initials right); content in one column; the next lesson panel first with its date and time large and tabular, then the week as register rows; a 64px bottom bar of four icon-and-label tabs plus More, above the safe-area inset. Desktop: the same items in a 240px clean-leaf rail on the left, content capped at 48rem.

FORM: Bottom tab bar (owner's choice, first of three offered: tab bar, drawer, home-as-menu); More opens a bottom sheet of ruled rows grouped by job; sign out moves to the account menu. seed:7dcbd104b2700c41 (rolled after the owner chose the structure through the question tool)

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
