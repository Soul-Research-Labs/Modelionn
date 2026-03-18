import { screen } from "@testing-library/react";
import { renderWithProviders } from "../helpers";

const mockProver = jest.fn();

jest.mock("@/lib/api", () => ({
  useProver: () => ({ data: mockProver(), isLoading: false }),
}));

jest.mock("next/navigation", () => ({
  useParams: () => ({
    hotkey: "5FLSigC9HGRKVhB9FiEo4Y3koPsNmBmLJbpXg2mp1hXcS59Y",
  }),
}));

jest.mock("next/link", () => {
  return function MockLink({
    children,
    href,
  }: {
    children: React.ReactNode;
    href: string;
  }) {
    return <a href={href}>{children}</a>;
  };
});

import ProverDetailPage from "@/app/provers/[hotkey]/page";

const sampleProver = {
  id: 1,
  hotkey: "5FLSigC9HGRKVhB9FiEo4Y3koPsNmBmLJbpXg2mp1hXcS59Y",
  gpu_name: "RTX 4090",
  gpu_backend: "cuda",
  gpu_count: 2,
  vram_bytes: 25769803776, // 24 GB
  benchmark_score: 95.2,
  supported_proof_types: "groth16,plonk",
  total_proofs: 1000,
  successful_proofs: 980,
  failed_proofs: 20,
  uptime_ratio: 0.995,
  online: true,
  stake: 100.5,
  last_seen: new Date().toISOString(),
};

describe("ProverDetailPage", () => {
  beforeEach(() => {
    mockProver.mockReturnValue(undefined);
  });

  it("shows 'Prover not found' when prover is null", () => {
    renderWithProviders(<ProverDetailPage />);
    expect(screen.getByText("Prover not found")).toBeInTheDocument();
  });

  it("renders prover hotkey", () => {
    mockProver.mockReturnValue(sampleProver);
    renderWithProviders(<ProverDetailPage />);
    expect(
      screen.getByText(
        "5FLSigC9HGRKVhB9FiEo4Y3koPsNmBmLJbpXg2mp1hXcS59Y",
      ),
    ).toBeInTheDocument();
  });

  it("displays online badge when prover is online", () => {
    mockProver.mockReturnValue(sampleProver);
    renderWithProviders(<ProverDetailPage />);
    expect(screen.getByText("Online")).toBeInTheDocument();
  });

  it("displays offline badge when prover is offline", () => {
    mockProver.mockReturnValue({ ...sampleProver, online: false });
    renderWithProviders(<ProverDetailPage />);
    expect(screen.getByText("Offline")).toBeInTheDocument();
  });

  it("shows GPU name in stat card", () => {
    mockProver.mockReturnValue(sampleProver);
    renderWithProviders(<ProverDetailPage />);
    expect(screen.getByText("RTX 4090")).toBeInTheDocument();
    expect(screen.getByText("GPU")).toBeInTheDocument();
  });

  it("shows benchmark score", () => {
    mockProver.mockReturnValue(sampleProver);
    renderWithProviders(<ProverDetailPage />);
    // Score appears in stat card and detail
    const benchmarkElements = screen.getAllByText("95.2");
    expect(benchmarkElements.length).toBeGreaterThanOrEqual(1);
  });

  it("displays uptime percentage", () => {
    mockProver.mockReturnValue(sampleProver);
    renderWithProviders(<ProverDetailPage />);
    // 0.995 * 100 = 99.5%
    const uptimeElements = screen.getAllByText("99.5%");
    expect(uptimeElements.length).toBeGreaterThanOrEqual(1);
  });

  it("shows hardware details card", () => {
    mockProver.mockReturnValue(sampleProver);
    renderWithProviders(<ProverDetailPage />);
    expect(screen.getByText("Hardware")).toBeInTheDocument();
    expect(screen.getByText("cuda")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument(); // gpu_count
  });

  it("shows supported proof types as badges", () => {
    mockProver.mockReturnValue(sampleProver);
    renderWithProviders(<ProverDetailPage />);
    expect(screen.getByText("groth16")).toBeInTheDocument();
    expect(screen.getByText("plonk")).toBeInTheDocument();
  });

  it("computes correct success rate", () => {
    mockProver.mockReturnValue(sampleProver);
    renderWithProviders(<ProverDetailPage />);
    // 980/1000 * 100 = 98.0%
    expect(screen.getByText("98.0%")).toBeInTheDocument();
  });

  it("shows back link to prover network", () => {
    mockProver.mockReturnValue(sampleProver);
    renderWithProviders(<ProverDetailPage />);
    const backLink = screen.getByRole("link", {
      name: /Back to Prover Network/i,
    });
    expect(backLink).toHaveAttribute("href", "/provers");
  });

  it("shows stake in tau", () => {
    mockProver.mockReturnValue(sampleProver);
    renderWithProviders(<ProverDetailPage />);
    expect(screen.getByText(/100\.5000.*τ/)).toBeInTheDocument();
  });

  it("handles zero total proofs for success rate", () => {
    mockProver.mockReturnValue({
      ...sampleProver,
      total_proofs: 0,
      successful_proofs: 0,
      failed_proofs: 0,
    });
    renderWithProviders(<ProverDetailPage />);
    expect(screen.getByText("0.0%")).toBeInTheDocument();
  });
});
