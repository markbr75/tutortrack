import { fireEvent, render, screen } from "@testing-library/react";

import { App } from "../App";
import { ME, mockApi } from "../test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  window.history.pushState(null, "", "/");
});

describe("AccountPage", () => {
  it("enrols an authenticator app and shows recovery codes", async () => {
    window.history.pushState(null, "", "/account");
    mockApi({
      "GET /api/v1/me": { body: ME },
      "GET /api/v1/organisation": { body: { status: "active" } },
      "GET /api/v1/me/organisations": { body: [] },
      "GET /api/v1/me/sessions": {
        body: [{ id: "s1", user_agent: "Firefox", is_current: true, last_seen_at: null }],
      },
      "POST /api/v1/me/mfa/totp": {
        body: {
          device_id: "d1",
          secret: "JBSWY3DPEHPK3PXP",
          otpauth_uri: "otpauth://totp/x",
          qr_svg: "<svg></svg>",
        },
      },
      "POST /api/v1/me/mfa/totp/confirm": {
        body: { recovery_codes: ["aaaaa-bbbbb", "ccccc-ddddd"] },
      },
    });
    render(<App />);
    expect(await screen.findByText("This device")).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "Set up authenticator app" }));
    expect(await screen.findByText("JBSWY3DPEHPK3PXP")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Enter the 6-digit code to confirm"), {
      target: { value: "123456" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Turn on" }));
    expect(await screen.findByText("aaaaa-bbbbb")).toBeInTheDocument();
  });
});
