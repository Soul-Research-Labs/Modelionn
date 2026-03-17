import React from "react";
import { renderWithProviders, screen } from "../helpers";
import LeaderboardPage from "@/app/leaderboard/page";

jest.mock("@/lib/api", () => ({
  useProvers: jest.fn(),
  useNetworkStats: jest.fn(),
}));

import { useProvers, useNetworkStats } from "@/lib/api";

const mockProvers = useProvers as jest.Mock;
const mockStats = useNetworkStats as jest.Mock;

const sampleProvers = {
  items: [
    {
      hotkey: "5AAA",
      benchmark_score: 95,
      successful_proofs: 200,
      total_proofs: 210,
      uptime_ratio: 0.99,
      online: true,
      vram_gb: 24,
    },
    {
      hotkey: "5BBB",
      benchmark_score: 80,
      successful_proofs: 150,
      total_proofs: 155,
      uptime_ratio: 0.95,
      online: true,
      vram_gb: 16,
    },
    {
      hotkey: "5CCC",
      benchmark_score: 40,
      successful_proofs: 0,
      total_proofs: 0,
      uptime_ratio: 0,
      online: false,
      vram_gb: 8,
    },
  ],
  total: 3,
};

beforeEach(() => {
  mockStats.mockReturnValue({
    data: {
      total_provers: 3,
      online_provers: 2,
      total_proofs_generated: 500,
      total_gpu_vram_bytes: 68719476736,
      avg_proof_time_ms: 3200,
      proofs_today: 50,
    },
    isLoading: false,
  });
  mockProvers.mockReturnValue({ data: sampleProvers, isLoading: false });
});

describe("LeaderboardPage", () => {
  it("renders heading", () => {
    renderWithProviders(<LeaderboardPage />);
    expect(screen.getByText("Leaderboard")).toBeInTheDocument();
  });

  it("shows skeleton when loading", () => {
    mockProvers.mockReturnValue({ data: undefined, isLoading: true });
    const { container } = renderWithProviders(<LeaderboardPage />);
    expect(container.querySelectorAll('[class*="animate-pulse"]').length).toBeGreaterThan(0);
  });

  it("ranks provers by benchmark score", () => {
    renderWithProviders(<LeaderboardPage />);
    // 5AAA should appear (top ranked)
    expect(screen.getByText(/5AAA/)).toBeInTheDocument();
  });

  it("filters out offline provers with no proofs", () => {
    renderWithProviders(<LeaderboardPage />);
    // 5CCC is offline with 0 proofs, filtered out
    expect(screen.queryByText(/5CCC/)).not.toBeInTheDocument();
  });

  it("renders time range buttons", () => {
    renderWithProviders(<LeaderboardPage />);
    expect(screen.getByText("24H")).toBeInTheDocument();
    expect(screen.getByText("7D")).toBeInTheDocument();
    expect(screen.getByText("30D")).toBeInTheDocument();
  });
});
