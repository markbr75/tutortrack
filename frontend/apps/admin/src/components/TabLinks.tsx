import { Link, type LinkProps } from "@tanstack/react-router";

/**
 * An area's own pages as a row of links ruled like tabs (the current page selected): body
 * size in faded ink, the current link ink at 600 with a 2px ink underline on the row's rule.
 */
export function TabLinks({
  label,
  links,
  className,
}: {
  label: string;
  links: ReadonlyArray<{ to: LinkProps["to"]; label: string; exact?: boolean }>;
  className?: string;
}) {
  return (
    <nav
      aria-label={label}
      className={`relative flex gap-1 overflow-x-auto border-b border-border [scrollbar-width:none] ${className ?? ""}`}
    >
      {links.map((l) => (
        <Link
          key={String(l.to)}
          to={l.to}
          activeOptions={{ exact: l.exact ?? false }}
          className="-mb-px shrink-0 border-b-2 border-transparent px-3 py-2 text-sm whitespace-nowrap text-muted-foreground hover:text-foreground [&.active]:border-foreground [&.active]:font-semibold [&.active]:text-foreground"
        >
          {l.label}
        </Link>
      ))}
    </nav>
  );
}
