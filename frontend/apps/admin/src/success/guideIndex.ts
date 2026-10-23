/** A section of an HTML guide that documents app pages (`data-route="admin:/calendar"`). */
export type GuideSection = { guide: string; id: string; routes: string[] };

/** The guide sections that name the app routes they document, in page order. The guides'
 * `data-route` convention is in docs/guides/README.md (`manage.py guides --check`). */
export function indexGuide(guide: string, html: string): GuideSection[] {
  const sections: GuideSection[] = [];
  for (const tag of html.matchAll(/<[a-z][a-z0-9]*\s[^>]*\bdata-route="([^"]+)"[^>]*>/gi)) {
    const id = /\sid="([^"]+)"/.exec(tag[0])?.[1];
    const routes = (tag[1] ?? "").split(/\s+/).filter(Boolean);
    if (id && routes.length) sections.push({ guide, id, routes });
  }
  return sections;
}

/** The section about a page: the longest documented route the path is at or under
 * (`/tutors` covers `/tutors/123`; `/` covers only Home). The first guide wins a tie. */
export function sectionFor(
  sections: GuideSection[],
  app: "admin" | "portal",
  pathname: string,
): GuideSection | null {
  const path = pathname.replace(/\/+$/, "") || "/";
  let best: { section: GuideSection; length: number } | null = null;
  for (const section of sections) {
    for (const route of section.routes) {
      const [routeApp, routePath] = route.split(":", 2);
      if (routeApp !== app || !routePath) continue;
      const covers =
        routePath === "/" ? path === "/" : path === routePath || path.startsWith(`${routePath}/`);
      if (covers && (!best || routePath.length > best.length)) {
        best = { section, length: routePath.length };
      }
    }
  }
  return best?.section ?? null;
}
