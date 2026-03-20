import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const pushMock = jest.fn();
const signInMock = jest.fn();

jest.mock("next-auth/react", () => ({
  signIn: (...args: unknown[]) => signInMock(...args),
}));

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
  useSearchParams: () => ({
    get: (key: string) => (key === "callbackUrl" ? "/proofs" : null),
  }),
}));

import SignInPage from "@/app/auth/signin/page";

describe("SignInPage", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    process.env.NEXT_PUBLIC_DEV_AUTH = "false";

    Object.defineProperty(global, "crypto", {
      value: {
        subtle: {
          digest: jest
            .fn()
            .mockResolvedValue(new Uint8Array([1, 2, 3, 4]).buffer),
        },
      },
      writable: true,
      configurable: true,
    });
  });

  it("renders wallet sign-in form", () => {
    render(<SignInPage />);

    expect(screen.getByText("Sign in to ZKML")).toBeTruthy();
    expect(screen.getByLabelText("Hotkey (SS58 Address)")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Connect Wallet" })).toBeTruthy();
  });

  it("shows error when dev auth is disabled", async () => {
    render(<SignInPage />);

    fireEvent.change(screen.getByLabelText("Hotkey (SS58 Address)"), {
      target: { value: "5GrwvaTestAddress" },
    });
    fireEvent.submit(screen.getByRole("button", { name: "Connect Wallet" }));

    const error = await screen.findByRole("alert");
    expect(error.textContent).toContain("Wallet signing required");
    expect(signInMock).not.toHaveBeenCalled();
  });

  it("calls wallet provider and redirects on successful sign-in", async () => {
    process.env.NEXT_PUBLIC_DEV_AUTH = "true";
    signInMock.mockResolvedValue({ ok: true });

    render(<SignInPage />);

    fireEvent.change(screen.getByLabelText("Hotkey (SS58 Address)"), {
      target: { value: "5D4vSuccess" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Connect Wallet" }));

    await waitFor(() => {
      expect(signInMock).toHaveBeenCalledTimes(1);
    });

    const [provider, payload] = signInMock.mock.calls[0] as [
      string,
      Record<string, unknown>,
    ];
    expect(provider).toBe("wallet");
    expect(payload.hotkey).toBe("5D4vSuccess");
    expect(payload.callbackUrl).toBe("/proofs");
    expect(payload.redirect).toBe(false);
    expect(typeof payload.signature).toBe("string");

    await waitFor(() => {
      expect(pushMock).toHaveBeenCalledWith("/proofs");
    });
  });

  it("shows auth failed error when wallet sign-in fails", async () => {
    process.env.NEXT_PUBLIC_DEV_AUTH = "true";
    signInMock.mockResolvedValue({ ok: false });

    render(<SignInPage />);

    fireEvent.change(screen.getByLabelText("Hotkey (SS58 Address)"), {
      target: { value: "5D4vFailure" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Connect Wallet" }));

    expect(
      await screen.findByText(
        "Authentication failed. Please check your hotkey.",
      ),
    ).toBeTruthy();
  });
});
