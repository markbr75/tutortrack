/** The shape of a pathway's stages as the editor holds them (E34 FR-34-2). The API checks
 * them again on save; these helpers keep keys unique and moves simple. */

export type Assignee = "participant" | "staff" | "family" | "system";

export type Question = {
  key: string;
  label: string;
  type: string;
  required?: boolean;
  options?: string[];
};

export type Step = {
  key: string;
  type: string;
  name: string;
  assignee?: Assignee;
  role?: string;
  due_days?: number | null;
  config: Record<string, unknown>;
};

export type Stage = { key: string; name: string; gate?: string; steps: Step[] };

export const QUESTION_TYPES = [
  "text",
  "textarea",
  "email",
  "phone",
  "number",
  "date",
  "select",
  "multiselect",
  "checkbox",
] as const;

/** A lower-case key not yet in ``taken``: ``base``, ``base_2``, ``base_3``... */
export function uniqueKey(base: string, taken: Iterable<string>): string {
  const used = new Set(taken);
  const root =
    base
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "")
      .replace(/^(\d)/, "s$1")
      .slice(0, 30) || "step";
  let key = root;
  for (let n = 2; used.has(key); n += 1) key = `${root}_${n}`;
  return key;
}

export function allStepKeys(stages: Stage[]): string[] {
  return stages.flatMap((stage) => stage.steps.map((step) => step.key));
}

/** The settings a new step of ``type`` starts with, so it saves straight away. */
export function defaultConfig(type: string): Record<string, unknown> {
  switch (type) {
    case "questions":
      return { fields: [{ key: "answer", label: "", type: "text", required: true }] };
    case "upload":
      return { instructions: "", max_files: 3, verify: true };
    case "sign":
      return { title: "", text: "" };
    case "acknowledge":
      return { title: "", text: "", link: "" };
    case "staff_review":
      return { question: "" };
    case "system_check":
      return { question: "" };
    case "show_check":
      return { requirement: "" };
    case "book_call":
      return { title: "", minutes: 30, days: 14 };
    default:
      return {};
  }
}

export function newStep(type: string, assignee: Assignee, taken: Iterable<string>): Step {
  return {
    key: uniqueKey(type, taken),
    type,
    name: "",
    assignee,
    role: "",
    due_days: null,
    config: defaultConfig(type),
  };
}

export function move<T>(items: T[], index: number, by: -1 | 1): T[] {
  const to = index + by;
  if (to < 0 || to >= items.length) return items;
  const out = [...items];
  const [item] = out.splice(index, 1);
  out.splice(to, 0, item as T);
  return out;
}
