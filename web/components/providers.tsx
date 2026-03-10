"use client";

import { SessionProvider } from "next-auth/react";
import {
  QueryClient,
  QueryClientProvider,
  MutationCache,
} from "@tanstack/react-query";
import { useState, useRef, useCallback } from "react";
import { ToastProvider, useToast } from "@/components/ui/toast";

function QueryProviderInner({ children }: { children: React.ReactNode }) {
  const { toast } = useToast();
  const toastRef = useRef(toast);
  toastRef.current = toast;

  const onMutationError = useCallback((error: Error) => {
    toastRef.current(error.message || "An error occurred", "error");
  }, []);

  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            retry: 2,
            refetchOnWindowFocus: false,
          },
        },
        mutationCache: new MutationCache({
          onError: onMutationError,
        }),
      }),
  );

  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <SessionProvider>
      <ToastProvider>
        <QueryProviderInner>{children}</QueryProviderInner>
      </ToastProvider>
    </SessionProvider>
  );
}
