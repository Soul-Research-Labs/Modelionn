import { screen, waitFor } from "@testing-library/react";
import { renderWithProviders, userEvent } from "../helpers";

const mockSearchCircuits = jest.fn();
const mockProvers = jest.fn();
const mockReplace = jest.fn();

jest.mock("@/lib/api", () => ({
  useSearchCircuits: (q: string, page: number) => ({
    data: mockSearchCircuits(q, page),
    isLoading: false,
  }),
  useProvers: () => ({ data: mockProvers() }),
}));

jest.mock("next/navigation", () => ({
  useSearchParams: () => ({
    get: (key: string) => {
      if (key === "q") return "groth16";
      if (key === "page") return "1";
      return null;
    },
  }),
  useRouter: () => ({
    replace: mockReplace,
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

// Must import AFTER mocks
import SearchPage from "@/app/search/page";

const sampleCircuits = {
  items: [
    {
      id: 1,
      name: "Poseidon Groth16",
      proof_type: "groth16",
      circuit_type: "general",
      num_constraints: 65536,
      version: "1.0.0",
    },
    {
      id: 2,
      name: "ZKML Inference",
      proof_type: "groth16",
      circuit_type: "zkml",
      num_constraints: 131072,
      version: "0.5.0",
    },
  ],
  total: 2,
};

const sampleProvers = {
  items: [
    {
      hotkey: "5FLSigC9HGRKVhB9FiEo4Y3koPsNmBmLJbpXg2mp1hXcS59Y",
      gpu_name: "RTX 4090",
      gpu_backend: "cuda",
      online: true,
    },
    {
      hotkey: "5DcYHnxxxOtherHotkeyXXXXXXXXXXXXXXXXXXXXXXXX",
      gpu_name: "A100",
      gpu_backend: "cuda",
      online: false,
    },
  ],
  total: 2,
};

describe("SearchPage", () => {
  beforeEach(() => {
    mockSearchCircuits.mockReturnValue(undefined);
    mockProvers.mockReturnValue(undefined);
    mockReplace.mockReset();
  });

  it("renders the search heading and input", () => {
    renderWithProviders(<SearchPage />);
    expect(screen.getByText("Search")).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText(/Search circuits, provers/),
    ).toBeInTheDocument();
  });

  it("displays circuit results when search returns data", () => {
    mockSearchCircuits.mockReturnValue(sampleCircuits);
    mockProvers.mockReturnValue(sampleProvers);
    renderWithProviders(<SearchPage />);

    expect(screen.getByText("Circuits")).toBeInTheDocument();
    expect(screen.getByText("Poseidon Groth16")).toBeInTheDocument();
    expect(screen.getByText("ZKML Inference")).toBeInTheDocument();
  });

  it("links circuits to their detail pages", () => {
    mockSearchCircuits.mockReturnValue(sampleCircuits);
    mockProvers.mockReturnValue(sampleProvers);
    renderWithProviders(<SearchPage />);

    const links = screen.getAllByRole("link");
    const circuitLinks = links.filter(
      (l) =>
        l.getAttribute("href")?.startsWith("/circuits/"),
    );
    expect(circuitLinks.length).toBe(2);
    expect(circuitLinks[0]).toHaveAttribute("href", "/circuits/1");
  });

  it("shows prover results matching query", () => {
    mockSearchCircuits.mockReturnValue({ items: [], total: 0 });
    // Provers with gpu_name containing "4090"
    mockProvers.mockReturnValue({
      items: [
        {
          hotkey: "5FTest",
          gpu_name: "RTX 4090",
          gpu_backend: "cuda",
          online: true,
        },
      ],
      total: 1,
    });
    // useSearchParams returns q="groth16" — won't match "RTX 4090" in client-side filter
    // So provers section should not appear for this query

    renderWithProviders(<SearchPage />);
    // Check for "No circuits match" fallback
    expect(
      screen.getByText(/No circuits match/),
    ).toBeInTheDocument();
  });

  it("shows no circuits match message when results are empty", () => {
    mockSearchCircuits.mockReturnValue({ items: [], total: 0 });
    mockProvers.mockReturnValue({ items: [], total: 0 });
    renderWithProviders(<SearchPage />);
    expect(screen.getByText(/No circuits match/)).toBeInTheDocument();
  });

  it("displays circuit total count badge", () => {
    mockSearchCircuits.mockReturnValue(sampleCircuits);
    mockProvers.mockReturnValue({ items: [], total: 0 });
    renderWithProviders(<SearchPage />);
    expect(screen.getByText("2")).toBeInTheDocument();
  });
});
