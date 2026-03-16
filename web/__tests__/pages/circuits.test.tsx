import { screen } from "@testing-library/react";
import { renderWithProviders, userEvent } from "../helpers";

const mockCircuits = jest.fn();
const mockUploadCircuit = jest.fn();

jest.mock("@/lib/api", () => ({
  useCircuits: () => ({
    data: mockCircuits(),
    isLoading: false,
  }),
  useUploadCircuit: () => ({
    mutateAsync: mockUploadCircuit,
    isPending: false,
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

import CircuitsPage from "@/app/circuits/page";

describe("CircuitsPage", () => {
  beforeEach(() => {
    mockCircuits.mockReturnValue(undefined);
    mockUploadCircuit.mockReset();
  });

  it("renders the Circuits heading and upload button", () => {
    renderWithProviders(<CircuitsPage />);
    expect(screen.getByText("Circuits")).toBeInTheDocument();
    expect(screen.getByText("Upload Circuit")).toBeInTheDocument();
  });

  it("shows empty state when no circuits exist", () => {
    mockCircuits.mockReturnValue({ items: [], total: 0 });
    renderWithProviders(<CircuitsPage />);
    expect(screen.getByText("No circuits uploaded yet")).toBeInTheDocument();
  });

  it("renders circuit cards when data is available", () => {
    mockCircuits.mockReturnValue({
      items: [
        {
          id: 1,
          name: "Test Groth16",
          proof_type: "groth16",
          circuit_type: "general",
          num_constraints: 65536,
          proofs_generated: 42,
          version: "1.0.0",
          circuit_hash: "bafy123abc",
        },
        {
          id: 2,
          name: "PLONK zkML",
          proof_type: "plonk",
          circuit_type: "zkml",
          num_constraints: 131072,
          proofs_generated: 10,
          version: "2.1.0",
          circuit_hash: "bafy456def",
        },
      ],
      total: 2,
    });

    renderWithProviders(<CircuitsPage />);
    expect(screen.getByText("Test Groth16")).toBeInTheDocument();
    expect(screen.getByText("PLONK zkML")).toBeInTheDocument();
    expect(screen.getByText("65.5K")).toBeInTheDocument();
    expect(screen.getByText("groth16")).toBeInTheDocument();
    expect(screen.getByText("plonk")).toBeInTheDocument();
  });

  it("renders filter chips for proof types and circuit types", () => {
    renderWithProviders(<CircuitsPage />);
    expect(screen.getByText("GROTH16")).toBeInTheDocument();
    expect(screen.getByText("PLONK")).toBeInTheDocument();
    expect(screen.getByText("HALO2")).toBeInTheDocument();
    expect(screen.getByText("STARK")).toBeInTheDocument();
  });

  it("opens upload modal when clicking Upload Circuit", async () => {
    const user = userEvent.setup();
    renderWithProviders(<CircuitsPage />);

    await user.click(screen.getByText("Upload Circuit"));
    // The upload modal should now be visible with form fields
    expect(screen.getByPlaceholderText("my-circuit")).toBeInTheDocument();
  });

  it("links each circuit card to its detail page", () => {
    mockCircuits.mockReturnValue({
      items: [
        {
          id: 7,
          name: "My Circuit",
          proof_type: "groth16",
          circuit_type: "general",
          num_constraints: 100,
          proofs_generated: 0,
          version: "1.0.0",
          circuit_hash: "bafyabc",
        },
      ],
      total: 1,
    });

    renderWithProviders(<CircuitsPage />);
    const link = screen.getByRole("link", { name: /My Circuit/i });
    expect(link).toHaveAttribute("href", "/circuits/7");
  });
});
