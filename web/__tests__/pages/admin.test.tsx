import React from "react";
import { renderWithProviders, screen } from "../helpers";
import AdminPage from "@/app/admin/page";

jest.mock("@/lib/api", () => ({
  useHealth: jest.fn(),
  useNetworkStats: jest.fn(),
  useProofJobs: jest.fn(),
  useProvers: jest.fn(),
}));

import { useHealth, useNetworkStats, useProofJobs, useProvers } from "@/lib/api";

const mockHealth = useHealth as jest.Mock;
const mockStats = useNetworkStats as jest.Mock;
const mockJobs = useProofJobs as jest.Mock;
const mockProvers = useProvers as jest.Mock;

beforeEach(() => {
  mockHealth.mockReturnValue({
    data: { status: "ok", version: "0.3.0", database: "ok", cache: "ok", network: "mainnet" },
    isLoading: false,
  });
  mockStats.mockReturnValue({
    data: {
      total_provers: 5,
      online_provers: 3,
      total_proofs_generated: 1234,
      total_gpu_vram_bytes: 0,
      avg_proof_time_ms: 0,
      proofs_today: 42,
    },
    isLoading: false,
  });
  mockJobs.mockReturnValue({
    data: { items: [], total: 0 },
    isLoading: false,
  });
  mockProvers.mockReturnValue({
    data: {
      items: [
        { hotkey: "5AA", online: true, benchmark_score: 90 },
        { hotkey: "5BB", online: false, benchmark_score: 50 },
      ],
      total: 2,
    },
    isLoading: false,
  });
});

describe("AdminPage", () => {
  it("renders heading", () => {
    renderWithProviders(<AdminPage />);
    expect(screen.getByText("Admin Dashboard")).toBeInTheDocument();
  });

  it("shows system health section", () => {
    renderWithProviders(<AdminPage />);
    expect(screen.getByText("System Health")).toBeInTheDocument();
    expect(screen.getByText("Registry API")).toBeInTheDocument();
  });

  it("shows skeleton when loading", () => {
    mockHealth.mockReturnValue({ data: undefined, isLoading: true });
    mockStats.mockReturnValue({ data: undefined, isLoading: true });
    const { container } = renderWithProviders(<AdminPage />);
    expect(container.querySelectorAll('[class*="animate-pulse"]').length).toBeGreaterThan(0);
  });

  it("displays prover overview", () => {
    renderWithProviders(<AdminPage />);
    expect(screen.getAllByText("Online Provers").length).toBeGreaterThan(0);
    expect(screen.getByText("Offline Provers")).toBeInTheDocument();
    expect(screen.getByText(/1 online \/ 1 offline/)).toBeInTheDocument();
  });
});
