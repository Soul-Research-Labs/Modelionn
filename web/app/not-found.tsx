"use client";

import Link from "next/link";
import { Button } from "@/components/ui/button";
import { FileQuestion } from "lucide-react";

export default function NotFound() {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center animate-fade-in">
      <FileQuestion className="h-16 w-16 text-gray-300" />
      <h1 className="mt-6 text-3xl font-bold tracking-tight text-gray-900">
        404
      </h1>
      <p className="mt-2 text-gray-500">
        The page you&apos;re looking for doesn&apos;t exist or has been moved.
      </p>
      <Link href="/" className="mt-6">
        <Button>Back to Dashboard</Button>
      </Link>
    </div>
  );
}
