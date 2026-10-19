import { render, screen } from "@testing-library/react";

import { RegisterMark } from "./RegisterMark";
import { registerMarkFor } from "./registerMarks";

describe("register marks", () => {
  const now = new Date("2026-10-19T15:00:00Z");

  it("follows the lesson's status, and whether it is over", () => {
    expect(registerMarkFor("completed", "2026-10-19T10:00:00Z", now)).toBe("completed");
    expect(registerMarkFor("missed", "2026-10-19T10:00:00Z", now)).toBe("missed");
    expect(registerMarkFor("cancelled", "2026-10-19T18:00:00Z", now)).toBe("cancelled");
    expect(registerMarkFor("planned", "2026-10-19T14:59:00Z", now)).toBe("due");
    expect(registerMarkFor("planned", "2026-10-19T15:00:00Z", now)).toBe("due");
    expect(registerMarkFor("planned", "2026-10-19T16:00:00Z", now)).toBe("upcoming");
  });

  it("is an image with a spoken label", () => {
    render(<RegisterMark kind="due" label="Not marked yet" />);
    expect(screen.getByRole("img", { name: "Not marked yet" })).toBeInTheDocument();
  });
});
