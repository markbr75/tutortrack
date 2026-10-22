import { RuledPanel } from "@tutortrack/ui";
import type { ReactNode } from "react";

/** A ruled panel for one part of the website screens (its title names the section). */
export function Card({
  title,
  description,
  aside,
  footer,
  children,
}: {
  title: string;
  description?: ReactNode;
  aside?: ReactNode;
  footer?: ReactNode;
  children: ReactNode;
}) {
  return (
    <RuledPanel
      title={title}
      description={description}
      aside={aside}
      footer={footer}
      bodyClassName="space-y-4"
    >
      {children}
    </RuledPanel>
  );
}
