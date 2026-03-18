import { screen } from "@testing-library/react";
import { renderWithProviders } from "../helpers";

const mockCircuit = jest.fn();
const mockProofs = jest.fn();
const mockRequestProof = jest.fn();

jest.mock("@/lib/api", () => ({
  useCircuit: () => ({ data: mockCircuit(), isLoading: false }),
  useProofs: () => ({ data: mockProofs() }),
  useRequestProof: () => ({
    mutate: mockRequestProof,
    isPending: false,
  }),
}));

jest.mock("next/navigation", () => ({
  useParams: () => ({ id: "5" }),
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

import CircuitDetailPage from "@/app/circuits/[id]/page";

const sampleCircuit = {
  id: 5,
  name: "Poseidon Hash Groth16",
  version: "2.1.0",
  proof_type: "groth16",
  circuit_type: "general",
  num_constraints: 131072,
  proofs_generated: 87,
  circuit_hash: "bafyhash123abc456",
  ipfs_cid: "bafycircuit789",
  proving_key_cid: "bafyprovingkey",
  verification_key_cid: "bafyverifykey",
  publisher_hotkey: "5FLSigC9HGRKVhB9FiEo4Y3koPsNmBmLJbpXg2mp1hXcS59Y",
  created_at: new Date().toISOString(),
};

describe("CircuitDetailPage", () => {
  beforeEach(() => {
    mockCircuit.mockReturnValue(undefined);
    mockProofs.mockReturnValue(undefined);
    mockRequestProof.mockReset();
  });

  it("shows 'Circuit not found' when circuit is null", () => {
    renderWithProviders(<CircuitDetailPage />);
    expect(screen.getByText("Circuit not found")).toBeInTheDocument();
  });

  it("renders circuit name and version", () => {
    mockCircuit.mockReturnValue(sampleCircuit);
    renderWithProviders(<CircuitDetailPage />);
    expect(screen.getByText("Poseidon Hash Groth16")).toBeInTheDocument();
    expect(screen.getByText(/v2\.1\.0/)).toBeInTheDocument();
  });

  it("displays proof type and circuit type badges", () => {
    mockCircuit.mockReturnValue(sampleCircuit);
    renderWithProviders(<CircuitDetailPage />);
    expect(screen.getByText("groth16")).toBeInTheDocument();
    expect(screen.getByText("general")).toBeInTheDocument();
  });

  it("displays stat cards for constraints and proofs", () => {
    mockCircuit.mockReturnValue(sampleCircuit);
    renderWithProviders(<CircuitDetailPage />);
    expect(screen.getByText("Constraints")).toBeInTheDocument();
    expect(screen.getByText("Proofs Generated")).toBeInTheDocument();
    expect(screen.getByText("GROTH16")).toBeInTheDocument();
  });

  it("renders circuit details with hashes", () => {
    mockCircuit.mockReturnValue(sampleCircuit);
    renderWithProviders(<CircuitDetailPage />);
    expect(screen.getByText("bafyhash123abc456")).toBeInTheDocument();
    expect(screen.getByText("bafycircuit789")).toBeInTheDocument();
    expect(screen.getByText("bafyprovingkey")).toBeInTheDocument();
    expect(screen.getByText("bafyverifykey")).toBeInTheDocument();
  });

  it("shows back link to circuits list", () => {
    mockCircuit.mockReturnValue(sampleCircuit);
    renderWithProviders(<CircuitDetailPage />);
    const backLink = screen.getByRole("link", { name: /Back to Circuits/i });
    expect(backLink).toHaveAttribute("href", "/circuits");
  });

  it("hides optional CID fields when not present", () => {
    const circuitWithoutKeys = {
      ...sampleCircuit,
      proving_key_cid: undefined,
      verification_key_cid: undefined,
    };
    mockCircuit.mockReturnValue(circuitWithoutKeys);
    renderWithProviders(<CircuitDetailPage />);
    expect(screen.queryByText("Proving Key CID")).not.toBeInTheDocument();
    expect(screen.queryByText("Verification Key CID")).not.toBeInTheDocument();
  });

  it("renders proofs table when proofs are available", () => {
    mockCircuit.mockReturnValue(sampleCircuit);
    mockProofs.mockReturnValue({
      items: [
        {
          id: 1,
          proof_hash: "0xabc123proof",
          gpu_backend: "cuda",
          generation_time_ms: 2500,
          verified: true,
          created_at: new Date().toISOString(),
        },
      ],
      total: 1,
    });
    renderWithProviders(<CircuitDetailPage />);
    expect(screen.getByText("Proofs (1)")).toBeInTheDocument();
    expect(screen.getByText("0xabc123proof")).toBeInTheDocument();
    expect(screen.getByText("cuda")).toBeInTheDocument();
    expect(screen.getByText("verified")).toBeInTheDocument();
  });

  it("shows 'New Proof Request' button", () => {
    mockCircuit.mockReturnValue(sampleCircuit);
    renderWithProviders(<CircuitDetailPage />);
    expect(screen.getByText("New Proof Request")).toBeInTheDocument();
  });
});
