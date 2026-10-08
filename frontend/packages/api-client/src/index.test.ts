import { describe, expect, it } from "vitest";

import { ApiError, unwrap } from "./index";

describe("unwrap", () => {
  it("returns data for successful responses", () => {
    const result = unwrap({ data: { ok: true }, response: new Response(null, { status: 200 }) });
    expect(result).toEqual({ ok: true });
  });

  it("throws ApiError carrying the problem details", () => {
    const problem = {
      type: "https://docs.tutortrack.app/problems/validation-error",
      title: "Validation failed",
      status: 400,
      errors: { name: ["This field is required."] },
    };
    let caught: unknown;
    try {
      unwrap({ error: problem, response: new Response(null, { status: 400 }) });
    } catch (err) {
      caught = err;
    }
    expect(caught).toBeInstanceOf(ApiError);
    expect((caught as ApiError).code).toBe("validation-error");
    expect((caught as ApiError).status).toBe(400);
    expect((caught as ApiError).problem.errors?.name).toHaveLength(1);
  });

  it("builds a problem from the HTTP status when the body is empty", () => {
    expect(() =>
      unwrap({ error: undefined, response: new Response(null, { status: 502 }) }),
    ).toThrow(ApiError);
  });
});
