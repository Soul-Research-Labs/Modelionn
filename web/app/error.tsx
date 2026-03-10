"use client";

import { useEffect } from "react";
import { Button } from "@/components/ui/button";
import { AlertTriangle } from "lucide-react";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("Unhandled error:", error);
  }, [error]);

  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center animate-fade-in">
      <div className="flex h-14 w-14 items-center justify-center rounded-full bg-red-100">
        <AlertTriangle className="h-7 w-7 text-red-600" />
      </div>
      <h1 className="mt-6 text-2xl font-bold tracking-tight text-gray-900">
        Something went wrong
      </h1>
      <p className="mt-2 max-w-md text-center text-gray-500">
        An unexpected error occurred. Please try again or contact support if the
        problem persists.
      </p>
      <Button onClick={reset} className="mt-6">
        Try Again
      </Button>
    </div>
  );
}
