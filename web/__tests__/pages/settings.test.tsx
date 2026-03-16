import { screen, waitFor } from "@testing-library/react";
import { renderWithProviders, userEvent } from "../helpers";

const mockApiKeys = jest.fn();
const mockCreateApiKey = jest.fn();
const mockRevokeApiKey = jest.fn();
const mockWebhooks = jest.fn();
const mockCreateWebhook = jest.fn();
const mockUpdateWebhook = jest.fn();
const mockDeleteWebhook = jest.fn();

jest.mock("@/lib/api", () => ({
  useApiKeys: () => ({ data: mockApiKeys(), isLoading: false }),
  useCreateApiKey: () => ({
    mutateAsync: mockCreateApiKey,
    isPending: false,
  }),
  useRevokeApiKey: () => ({
    mutateAsync: mockRevokeApiKey,
    isPending: false,
  }),
  useWebhooks: () => ({ data: mockWebhooks(), isLoading: false }),
  useCreateWebhook: () => ({
    mutateAsync: mockCreateWebhook,
    isPending: false,
  }),
  useUpdateWebhook: () => ({
    mutateAsync: mockUpdateWebhook,
    isPending: false,
  }),
  useDeleteWebhook: () => ({
    mutateAsync: mockDeleteWebhook,
    isPending: false,
  }),
}));

jest.mock("next-auth/react", () => ({
  useSession: () => ({
    data: { user: { name: "5FHneW46..." } },
    status: "authenticated",
  }),
}));

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: jest.fn() }),
}));

import SettingsPage from "@/app/settings/page";

describe("SettingsPage", () => {
  beforeEach(() => {
    mockApiKeys.mockReturnValue(undefined);
    mockCreateApiKey.mockReset();
    mockRevokeApiKey.mockReset();
    mockWebhooks.mockReturnValue([]);
    mockCreateWebhook.mockReset();
    mockUpdateWebhook.mockReset();
    mockDeleteWebhook.mockReset();
  });

  it("renders the Settings heading and profile section", () => {
    renderWithProviders(<SettingsPage />);
    expect(screen.getByText("Settings")).toBeInTheDocument();
    expect(screen.getByText("Profile")).toBeInTheDocument();
    expect(screen.getByText("5FHneW46...")).toBeInTheDocument();
  });

  it("renders API Keys section with create button", () => {
    renderWithProviders(<SettingsPage />);
    expect(screen.getByText("API Keys")).toBeInTheDocument();
    expect(screen.getByText("Create Key")).toBeInTheDocument();
  });

  it("shows API keys in a list when data is loaded", () => {
    mockApiKeys.mockReturnValue([
      {
        id: 1,
        label: "CI pipeline",
        key_prefix: "mk_test_abc",
        created_at: new Date().toISOString(),
        is_active: true,
        daily_limit: 1000,
        usage_today: 42,
      },
      {
        id: 2,
        label: "Dev local",
        key_prefix: "mk_test_xyz",
        created_at: new Date().toISOString(),
        is_active: true,
        daily_limit: 500,
        usage_today: 0,
      },
    ]);

    renderWithProviders(<SettingsPage />);
    expect(screen.getByText("CI pipeline")).toBeInTheDocument();
    expect(screen.getByText("Dev local")).toBeInTheDocument();
  });

  it("toggles create form when clicking Create Key", async () => {
    const user = userEvent.setup();
    renderWithProviders(<SettingsPage />);

    await user.click(screen.getByText("Create Key"));
    expect(screen.getByPlaceholderText("e.g. CI pipeline")).toBeInTheDocument();
    expect(screen.getByText("Daily Limit")).toBeInTheDocument();
  });

  it("displays the hotkey from session", () => {
    renderWithProviders(<SettingsPage />);
    const hotkeyEl = screen.getByText("5FHneW46...");
    expect(hotkeyEl).toBeInTheDocument();
  });
});
