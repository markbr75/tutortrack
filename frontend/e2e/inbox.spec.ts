/**
 * Communications inbox (E13) with the AI assistant (E31): a parent writes from the portal,
 * a coordinator answers with a canned reply and an AI-suggested draft (the deterministic
 * fake provider; no network), and the parent sees the answer. Test plan: TP-E13, TP-E31.
 */
import { PORTAL, expect, test, uid } from "./fixtures";

test("a portal message is answered from the inbox with a suggested reply", async ({ pageAs }) => {
  const subject = `Half-term swap ${uid()}`;

  // Priya writes to the office from the portal.
  const parent = await pageAs("parent");
  await parent.goto(`${PORTAL}messages`);
  await parent.getByRole("button", { name: "New message" }).click();
  const compose = parent.getByRole("form", { name: "New message" });
  await compose.getByLabel("Subject").fill(subject);
  await compose.getByLabel("Your message").fill("Could Arjun's lesson move to 5pm next Tuesday?");
  await compose.getByRole("button", { name: "Send" }).click();
  await expect(parent.getByRole("heading", { name: subject })).toBeVisible();

  // The coordinator finds it in the inbox.
  const staff = await pageAs("coordinator");
  await staff.goto("/inbox");
  await staff.getByRole("searchbox", { name: "Search conversations" }).fill(subject);
  const conversation = staff
    .getByRole("list", { name: "Conversations" })
    .getByRole("button", { name: new RegExp(subject) });
  await conversation.click();
  await expect(staff.getByRole("heading", { name: subject })).toBeVisible();

  // An AI draft (fake provider) fills the message box; staff review and send it.
  const reply = staff.getByRole("form", { name: "Reply" });
  await staff.getByRole("button", { name: "Suggest reply" }).click();
  await expect(reply.getByLabel("Message")).not.toHaveValue("");
  const suggested = await reply.getByLabel("Message").inputValue();
  // Grounded in the family's data: the fake model quotes Arjun's next lesson.
  expect(suggested).toMatch(/thanks for your message/i);
  expect(suggested).toMatch(/Arjun Patel/);

  // A canned reply is added to the draft; staff send the result.
  await reply.getByLabel("Canned reply").selectOption({ label: "Tutor confirmed" });
  await expect(reply.getByLabel("Message")).toHaveValue(/your tutor is confirmed/);
  await reply.getByRole("button", { name: "Send", exact: true }).click();
  await expect(
    staff.getByRole("region", { name: subject }).getByText(/your tutor is confirmed/),
  ).toBeVisible();

  // Priya sees the answer in the portal.
  await parent.reload();
  await parent
    .getByRole("list", { name: "Conversations" })
    .getByRole("button", { name: new RegExp(subject) })
    .click();
  await expect(
    parent.getByRole("region", { name: subject }).getByText(/your tutor is confirmed/),
  ).toBeVisible();
});

test("an internal note stays inside the team", async ({ pageAs }) => {
  const subject = `Invoice question ${uid()}`;
  const parent = await pageAs("parent");
  await parent.goto(`${PORTAL}messages`);
  await parent.getByRole("button", { name: "New message" }).click();
  const compose = parent.getByRole("form", { name: "New message" });
  await compose.getByLabel("Subject").fill(subject);
  await compose.getByLabel("Your message").fill("Is the October invoice right?");
  await compose.getByRole("button", { name: "Send" }).click();
  await expect(parent.getByRole("heading", { name: subject })).toBeVisible();

  const staff = await pageAs("coordinator");
  await staff.goto("/inbox");
  await staff.getByRole("searchbox", { name: "Search conversations" }).fill(subject);
  await staff
    .getByRole("list", { name: "Conversations" })
    .getByRole("button", { name: new RegExp(subject) })
    .click();
  const note = `Checked with finance ${uid()}`;
  const reply = staff.getByRole("form", { name: "Reply" });
  await reply.getByLabel("Message").fill(note);
  await reply.getByRole("button", { name: "Add internal note" }).click();
  await expect(staff.getByRole("region", { name: subject }).getByText(note)).toBeVisible();

  await parent.reload();
  await parent
    .getByRole("list", { name: "Conversations" })
    .getByRole("button", { name: new RegExp(subject) })
    .click();
  await expect(parent.getByRole("heading", { name: subject })).toBeVisible();
  await expect(parent.getByText(note)).toHaveCount(0);
});
