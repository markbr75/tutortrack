import { Fragment, type ReactNode } from "react";

/**
 * The small markdown subset used by help articles (E30 FR-30-5): headings, paragraphs,
 * ordered and unordered lists, **bold** and [links](/path). Rendered as React elements
 * (no HTML injection); only same-site paths and https links are made into links.
 */
function inline(text: string, keyPrefix: string): ReactNode[] {
  const out: ReactNode[] = [];
  const pattern = /\*\*([^*]+)\*\*|\[([^\]]+)\]\(([^)\s]+)\)/g;
  let last = 0;
  let match: RegExpExecArray | null;
  let n = 0;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) out.push(text.slice(last, match.index));
    const key = `${keyPrefix}-${n++}`;
    if (match[1] !== undefined) {
      out.push(<strong key={key}>{match[1]}</strong>);
    } else {
      const href = match[3] ?? "";
      const safe = (href.startsWith("/") && !href.startsWith("//")) || href.startsWith("https://");
      out.push(
        safe ? (
          <a
            key={key}
            href={href}
            className="font-medium text-link underline-offset-2 hover:underline"
          >
            {match[2]}
          </a>
        ) : (
          <Fragment key={key}>{match[2]}</Fragment>
        ),
      );
    }
    last = pattern.lastIndex;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

type Block =
  | { kind: "heading"; level: number; text: string }
  | { kind: "paragraph"; text: string }
  | { kind: "list"; ordered: boolean; items: string[] };

function parseBlocks(source: string): Block[] {
  const blocks: Block[] = [];
  let paragraph: string[] = [];
  let list: { ordered: boolean; items: string[] } | null = null;
  const endParagraph = () => {
    if (paragraph.length) blocks.push({ kind: "paragraph", text: paragraph.join(" ") });
    paragraph = [];
  };
  const endList = () => {
    if (list) blocks.push({ kind: "list", ...list });
    list = null;
  };
  for (const raw of source.split("\n")) {
    const line = raw.trim();
    const heading = /^(#{1,3})\s+(.*)$/.exec(line);
    const bullet = /^[-*]\s+(.*)$/.exec(line);
    const numbered = /^\d+\.\s+(.*)$/.exec(line);
    if (!line) {
      endParagraph();
      endList();
    } else if (heading) {
      endParagraph();
      endList();
      blocks.push({ kind: "heading", level: heading[1]!.length, text: heading[2]! });
    } else if (bullet || numbered) {
      endParagraph();
      const ordered = Boolean(numbered);
      const current = list as { ordered: boolean; items: string[] } | null;
      if (current && current.ordered !== ordered) endList();
      list ??= { ordered, items: [] };
      list.items.push((bullet ?? numbered)![1]!);
    } else if (list) {
      const items = (list as { items: string[] }).items;
      items[items.length - 1] += ` ${line}`;
    } else {
      paragraph.push(line);
    }
  }
  endParagraph();
  endList();
  return blocks;
}

export function Markdown({ source, headingLevel = 3 }: { source: string; headingLevel?: number }) {
  return (
    <div className="space-y-3 text-sm leading-relaxed">
      {parseBlocks(source).map((block, i) => {
        const key = `b${i}`;
        if (block.kind === "heading") {
          const level = Math.min(6, headingLevel + block.level - 1);
          const Tag = `h${level}` as "h3";
          return (
            <Tag key={key} className="font-semibold">
              {inline(block.text, key)}
            </Tag>
          );
        }
        if (block.kind === "list") {
          const List = block.ordered ? "ol" : "ul";
          return (
            <List key={key} className={block.ordered ? "list-decimal pl-5" : "list-disc pl-5"}>
              {block.items.map((item, j) => (
                <li key={`${key}-${j}`}>{inline(item, `${key}-${j}`)}</li>
              ))}
            </List>
          );
        }
        return <p key={key}>{inline(block.text, key)}</p>;
      })}
    </div>
  );
}
