import { indexGuide, sectionFor } from "./guideIndex";

const USER = `
<section id="home" data-route="admin:/" aria-labelledby="home-h"><h2>Home</h2></section>
<section id="people-lists" data-route="admin:/clients admin:/students admin:/tutors">x</section>
<section data-route="admin:/nowhere">no id, so not linkable</section>
<section aria-labelledby="t" id="tutor-today" data-route="portal:/tutor">y</section>`;
const ADMIN = `<section id="plan" data-route="admin:/settings/plan">z</section>
<section id="settings" data-route="admin:/settings">s</section>`;

describe("the guides' page index", () => {
  const sections = [
    ...indexGuide("user-guide.html", USER),
    ...indexGuide("admin-guide.html", ADMIN),
  ];

  it("reads every section that names its routes, in either attribute order", () => {
    expect(sections.map((s) => s.id)).toEqual([
      "home",
      "people-lists",
      "tutor-today",
      "plan",
      "settings",
    ]);
    expect(sections[1]?.routes).toEqual(["admin:/clients", "admin:/students", "admin:/tutors"]);
  });

  it("finds the section for a page, its records and the longest matching route", () => {
    expect(sectionFor(sections, "admin", "/tutors")?.id).toBe("people-lists");
    expect(sectionFor(sections, "admin", "/tutors/t1")?.id).toBe("people-lists");
    expect(sectionFor(sections, "admin", "/settings/plan")?.id).toBe("plan");
    expect(sectionFor(sections, "admin", "/settings/other")?.id).toBe("settings");
    expect(sectionFor(sections, "admin", "/")?.id).toBe("home");
    // Home covers only itself, and routes are per app.
    expect(sectionFor(sections, "admin", "/calendar")).toBeNull();
    expect(sectionFor(sections, "admin", "/tutor")).toBeNull();
    expect(sectionFor(sections, "portal", "/tutor/schedule")?.id).toBe("tutor-today");
  });
});
