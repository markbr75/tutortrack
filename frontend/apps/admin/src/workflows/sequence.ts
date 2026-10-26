/**
 * The sequence a workflow is (E33 FR-33-1), as the editor shows it: a list of cards on one
 * timeline. A card is "When" (an optional wait), "Only if" (one plain question) and "Do" (one
 * or more actions); a split card asks one question and has a Yes and a No path of cards.
 *
 * The engine stores a flat list of steps (wait, action, branch). ``toCards`` groups them into
 * cards and ``toSteps`` writes them back without changing anything that wasn't edited, so a
 * built-in saved untouched still matches its default.
 */

export type Condition = {
  predicate?: string;
  field?: string;
  op?: string;
  value?: unknown;
  all?: Condition[];
  any?: Condition[];
};

export type Step = {
  type: "action" | "wait" | "branch";
  action?: string;
  config?: Record<string, unknown>;
  only_if?: Condition;
  minutes?: number;
  hours?: number;
  days?: number;
  until?: string;
  offset_days?: number;
  offset_hours?: number;
  at?: string;
  business_day?: boolean;
  quiet_hours?: boolean;
  if?: Condition;
  then?: Step[];
  else?: Step[];
};

export type DoCard = { kind: "do"; wait: Step | null; onlyIf: Condition | null; actions: Step[] };
export type SplitCard = {
  kind: "split";
  wait: Step | null;
  question: Condition | null;
  yes: DoCard[];
  no: DoCard[];
};
export type Card = DoCard | SplitCard;

export const MAX_SPLITS = 5;
export const MAX_STOPS = 3;

const same = (a: unknown, b: unknown) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);

/** A copy of the step without these keys. */
export function omit(step: Step, ...keys: (keyof Step)[]): Step {
  const out = { ...step };
  for (const key of keys) delete out[key];
  return out;
}

const withoutOnlyIf = (step: Step): Step => omit(step, "only_if");

/** Whether the editor can show these steps: splits only at the top, one level deep. */
export function fits(steps: Step[], depth = 0): boolean {
  return steps.every((s) => {
    if (s.type !== "branch") return true;
    if (depth > 0) return false;
    return fits(s.then ?? [], 1) && fits(s.else ?? [], 1);
  });
}

export function toCards(steps: Step[]): Card[] {
  const cards: Card[] = [];
  let current: DoCard | null = null;
  const close = () => {
    if (current) cards.push(current);
    current = null;
  };
  for (const step of steps) {
    if (step.type === "wait") {
      close();
      current = { kind: "do", wait: step, onlyIf: null, actions: [] };
    } else if (step.type === "action") {
      const onlyIf = step.only_if ?? null;
      const open = current as DoCard | null;
      if (open && (open.actions.length === 0 || same(open.onlyIf, onlyIf))) {
        open.onlyIf = onlyIf;
        open.actions.push(withoutOnlyIf(step));
      } else {
        close();
        current = { kind: "do", wait: null, onlyIf, actions: [withoutOnlyIf(step)] };
      }
    } else {
      const open = current as DoCard | null;
      const wait = open && open.actions.length === 0 ? open.wait : null;
      if (open && open.actions.length > 0) close();
      current = null;
      cards.push({
        kind: "split",
        wait,
        question: step.if ?? null,
        yes: toCards(step.then ?? []).filter((c): c is DoCard => c.kind === "do"),
        no: toCards(step.else ?? []).filter((c): c is DoCard => c.kind === "do"),
      });
    }
  }
  close();
  return cards;
}

export function toSteps(cards: Card[]): Step[] {
  return cards.flatMap((card): Step[] => {
    const wait = card.wait ? [card.wait] : [];
    if (card.kind === "split") {
      return [
        ...wait,
        {
          type: "branch",
          if: card.question ?? {},
          then: toSteps(card.yes),
          else: toSteps(card.no),
        },
      ];
    }
    const onlyIf = card.onlyIf;
    return [...wait, ...card.actions.map((a) => (onlyIf ? { ...a, only_if: onlyIf } : a))];
  });
}

export const newCard = (): DoCard => ({ kind: "do", wait: null, onlyIf: null, actions: [] });
export const newSplit = (): SplitCard => ({
  kind: "split",
  wait: null,
  question: null,
  yes: [newCard()],
  no: [],
});

export function countSplits(cards: Card[]): number {
  return cards.filter((c) => c.kind === "split").length;
}

export function moveItem<T>(items: T[], index: number, by: number): T[] {
  const next = [...items];
  const [item] = next.splice(index, 1);
  if (item !== undefined) next.splice(Math.max(0, Math.min(next.length, index + by)), 0, item);
  return next;
}

/** The plain questions a condition is made of, or null when it uses field checks. */
export function questionsOf(condition: Condition | null | undefined): string[] | null {
  if (!condition || Object.keys(condition).length === 0) return [];
  if (condition.predicate) return [condition.predicate];
  if (condition.all && condition.all.every((c) => c.predicate && Object.keys(c).length === 1)) {
    return condition.all.map((c) => c.predicate as string);
  }
  return null;
}

export function fromQuestions(keys: string[]): Condition {
  if (keys.length === 0) return {};
  if (keys.length === 1) return { predicate: keys[0] };
  return { all: keys.map((predicate) => ({ predicate })) };
}

// --- waits -------------------------------------------------------------------------------------

export type WaitMode = "now" | "after" | "date";

export function waitMode(wait: Step | null): WaitMode {
  if (!wait) return "now";
  return wait.until ? "date" : "after";
}

/** "after" waits in one unit: the editor offers minutes, hours or days (the engine counts
 * minutes as part hours). */
export function waitAmount(wait: Step): { amount: number; unit: "minutes" | "hours" | "days" } {
  if (wait.days && !wait.hours && !wait.minutes) return { amount: wait.days, unit: "days" };
  const total = Math.round(((wait.days ?? 0) * 24 + (wait.hours ?? 0)) * 60 + (wait.minutes ?? 0));
  if (total % 60 === 0) return { amount: total / 60, unit: "hours" };
  return { amount: total, unit: "minutes" };
}

export function setWaitAmount(wait: Step, amount: number, unit: "minutes" | "hours" | "days") {
  const rest = omit(wait, "days", "hours", "minutes", "until", "offset_days", "offset_hours");
  if (unit === "minutes") return { ...rest, hours: amount / 60 };
  return { ...rest, [unit]: amount };
}

/** Days or hours before (negative) or after the date. */
export function dateOffset(wait: Step): { amount: number; unit: "days" | "hours" } {
  if (wait.offset_hours && !wait.offset_days) return { amount: wait.offset_hours, unit: "hours" };
  return { amount: wait.offset_days ?? 0, unit: "days" };
}

export function setDateOffset(wait: Step, amount: number, unit: "days" | "hours"): Step {
  const rest = omit(wait, "offset_days", "offset_hours", "days", "hours", "minutes");
  return unit === "days" ? { ...rest, offset_days: amount } : { ...rest, offset_hours: amount };
}

// --- starts ------------------------------------------------------------------------------------

export type StartKind = "event" | "schedule" | "date" | "manual";

/** A date start counts in days ("offset_days") or, near a date and time, in minutes. */
export function startOffsets(config: Record<string, unknown>): {
  values: number[];
  unit: "days" | "minutes";
} {
  if (Array.isArray(config.minutes)) return { values: config.minutes as number[], unit: "minutes" };
  const raw = config.offset_days;
  const values = Array.isArray(raw) ? (raw as number[]) : [Number(raw ?? 0)];
  return { values, unit: "days" };
}

// --- problems ----------------------------------------------------------------------------------

export type ActionDef = {
  key: string;
  label: string;
  fields: { name: string; label: string; type: string; required: boolean }[];
};

export type Problem =
  | { code: "chooseAction" }
  | { code: "fillIn"; field: string }
  | { code: "chooseMessage" }
  | { code: "chooseDate" }
  | { code: "howLong" }
  | { code: "badTime" }
  | { code: "chooseQuestion" }
  | { code: "emptyPath" };

const TIME = /^([01]\d|2[0-3]):[0-5]\d$/;

function empty(value: unknown): boolean {
  if (value === undefined || value === null || value === "") return true;
  return Array.isArray(value) && value.length === 0;
}

export function waitProblems(wait: Step | null): Problem[] {
  if (!wait) return [];
  const out: Problem[] = [];
  if (wait.until !== undefined) {
    if (!wait.until) out.push({ code: "chooseDate" });
  } else {
    const total = (wait.days ?? 0) * 24 + (wait.hours ?? 0) + (wait.minutes ?? 0) / 60;
    if (!(total > 0) && !wait.at) out.push({ code: "howLong" });
  }
  if (wait.at !== undefined && !TIME.test(wait.at)) out.push({ code: "badTime" });
  return out;
}

export function actionProblems(step: Step, actions: ActionDef[]): Problem[] {
  const action = actions.find((a) => a.key === step.action);
  if (!action) return [{ code: "chooseAction" }];
  const config = step.config ?? {};
  return action.fields
    .filter((f) => f.required && empty(config[f.name]))
    .map((f) =>
      ["template", "saved_reply", "whatsapp_template"].includes(f.type)
        ? { code: "chooseMessage" as const }
        : { code: "fillIn" as const, field: f.label },
    );
}

export function cardProblems(card: Card, actions: ActionDef[]): Problem[] {
  const out = waitProblems(card.wait);
  if (card.kind === "split") {
    if (!card.question || questionsOf(card.question)?.length === 0) {
      out.push({ code: "chooseQuestion" });
    }
    if (card.yes.length === 0 && card.no.length === 0) out.push({ code: "emptyPath" });
    return out;
  }
  if (card.actions.length === 0) out.push({ code: "chooseAction" });
  for (const step of card.actions) out.push(...actionProblems(step, actions));
  return out;
}

/** Every problem in the sequence, the split paths' cards included. */
export function allProblems(cards: Card[], actions: ActionDef[]): Problem[] {
  return cards.flatMap((card) => [
    ...cardProblems(card, actions),
    ...(card.kind === "split"
      ? [...card.yes, ...card.no].flatMap((c) => cardProblems(c, actions))
      : []),
  ]);
}
