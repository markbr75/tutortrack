import {
  allProblems,
  fits,
  fromQuestions,
  moveItem,
  newCard,
  questionsOf,
  setWaitAmount,
  toCards,
  toSteps,
  waitAmount,
  type ActionDef,
  type Step,
} from "./sequence";

const act = (action: string, extra: Partial<Step> = {}): Step => ({
  type: "action",
  action,
  config: {},
  ...extra,
});
const at = (offset_days: number): Step => ({
  type: "wait",
  until: "invoice.due_date",
  offset_days,
  at: "09:00",
});

// The payment chasing and enquiry follow-up built-ins, as the API returns them.
const CHASING: Step[] = [at(-3), act("send_invoice_reminder"), at(0), act("send_invoice_reminder"),
  at(14), act("late_fee")]; // prettier-ignore
const FOLLOW_UP: Step[] = [
  act("thank_for_enquiry"),
  act("tell_enquiry_owner"),
  { type: "wait", until: "enquiry.stage_deadline", offset_hours: 0 },
  act("flag_enquiry_waiting", { only_if: { predicate: "enquiry.stage_has_time_limit" } }),
];
const SPLIT: Step[] = [
  { type: "wait", days: 1 },
  {
    type: "branch",
    if: { predicate: "invoice.unpaid" },
    then: [act("send_invoice_reminder"), { type: "wait", days: 2 }, act("collect_payment")],
    else: [],
  },
  act("add_tag", { config: { tag: "Chased" } }),
];

describe("cards from steps and back", () => {
  it.each([
    ["payment chasing", CHASING],
    ["enquiry follow-up", FOLLOW_UP],
    ["a split", SPLIT],
  ])("keeps %s exactly as it was", (_name, steps) => {
    expect(toSteps(toCards(steps))).toEqual(steps);
  });

  it("makes a card of each wait and the actions after it", () => {
    const cards = toCards(FOLLOW_UP);
    expect(cards).toHaveLength(2);
    expect(cards[0]).toMatchObject({ wait: null, onlyIf: null });
    expect(cards[0]?.kind === "do" && cards[0].actions.map((a) => a.action)).toEqual([
      "thank_for_enquiry",
      "tell_enquiry_owner",
    ]);
    expect(cards[1]).toMatchObject({
      wait: { until: "enquiry.stage_deadline" },
      onlyIf: { predicate: "enquiry.stage_has_time_limit" },
    });
  });

  it("puts a wait just before a split on the split, and keeps the paths' cards", () => {
    const [split, after] = toCards(SPLIT);
    expect(split).toMatchObject({ kind: "split", wait: { days: 1 } });
    expect(split?.kind === "split" && split.yes).toHaveLength(2);
    expect(after).toMatchObject({ kind: "do", wait: null });
  });

  it("starts a new card when the only-if changes", () => {
    const steps = [act("a"), act("b", { only_if: { predicate: "invoice.unpaid" } })];
    expect(toCards(steps)).toHaveLength(2);
    expect(toSteps(toCards(steps))).toEqual(steps);
  });

  it("can't show splits inside splits", () => {
    expect(fits(SPLIT)).toBe(true);
    const nested = [{ type: "branch", if: {}, then: SPLIT, else: [] } as Step];
    expect(fits(nested)).toBe(false);
  });
});

describe("plain questions", () => {
  it("reads one, several or none, and gives up on field checks", () => {
    expect(questionsOf({})).toEqual([]);
    expect(questionsOf({ predicate: "package.active" })).toEqual(["package.active"]);
    expect(
      questionsOf({
        all: [{ predicate: "package.active" }, { predicate: "package.has_units_left" }],
      }),
    ).toEqual(["package.active", "package.has_units_left"]);
    expect(questionsOf({ field: "student.status", op: "equals", value: "x" })).toBeNull();
    expect(fromQuestions(["a", "b"])).toEqual({ all: [{ predicate: "a" }, { predicate: "b" }] });
    expect(fromQuestions(["a"])).toEqual({ predicate: "a" });
  });
});

describe("waits", () => {
  it("shows a wait in one unit", () => {
    expect(waitAmount({ type: "wait", days: 3 })).toEqual({ amount: 3, unit: "days" });
    expect(waitAmount({ type: "wait", hours: 48 })).toEqual({ amount: 48, unit: "hours" });
    expect(waitAmount({ type: "wait", hours: 0.5 })).toEqual({ amount: 30, unit: "minutes" });
    expect(setWaitAmount({ type: "wait", days: 1, at: "09:00" }, 90, "minutes")).toEqual({
      type: "wait",
      hours: 1.5,
      at: "09:00",
    });
  });
});

describe("problems in words", () => {
  const actions: ActionDef[] = [
    { key: "send_message", label: "Send a message", fields: [
      { name: "to", label: "To", type: "multi", required: true },
      { name: "body", label: "Message", type: "template", required: true },
    ] },
    { key: "add_tag", label: "Add a tag", fields: [] },
  ]; // prettier-ignore

  it("says what each card is missing", () => {
    const problems = allProblems(
      [
        newCard(),
        { kind: "do", wait: { type: "wait", until: "" }, onlyIf: null, actions: [act("add_tag")] },
        { kind: "do", wait: null, onlyIf: null, actions: [act("send_message")] },
        { kind: "split", wait: null, question: null, yes: [newCard()], no: [] },
      ],
      actions,
    );
    expect(problems).toEqual([
      { code: "chooseAction" },
      { code: "chooseDate" },
      { code: "fillIn", field: "To" },
      { code: "chooseMessage" },
      { code: "chooseQuestion" },
      { code: "chooseAction" },
    ]);
    expect(allProblems(toCards(CHASING), [...actions,
      { key: "send_invoice_reminder", label: "", fields: [] },
      { key: "late_fee", label: "", fields: [] }])).toEqual([]); // prettier-ignore
  });
});

it("moves an item up or down", () => {
  expect(moveItem(["a", "b", "c"], 2, -1)).toEqual(["a", "c", "b"]);
  expect(moveItem(["a", "b"], 0, -1)).toEqual(["a", "b"]);
});
