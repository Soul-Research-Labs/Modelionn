import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "@/components/providers";
import { Sidebar } from "@/components/sidebar";
import { Header } from "@/components/header";
import { ErrorBoundary } from "@/components/error-boundary";

export const metadata: Metadata = {
  title: "Modelionn — Open Intelligence Registry",
  description:
    "The Open Intelligence Registry — publish, discover, and evaluate AI models, datasets & benchmarks on Bittensor.",
  icons: {
    icon: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="font-sans antialiased">
        <Providers>
          <a
            href="#main-content"
            className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:rounded-md focus:bg-brand-600 focus:px-4 focus:py-2 focus:text-white"
          >
            Skip to content
          </a>
          <div className="flex h-screen overflow-hidden">
            <Sidebar />
            <div className="flex flex-1 flex-col overflow-hidden">
              <Header />
              <main id="main-content" className="flex-1 overflow-y-auto p-6">
                <ErrorBoundary>{children}</ErrorBoundary>
              </main>
            </div>
          </div>
        </Providers>
      </body>
    </html>
  );
}
