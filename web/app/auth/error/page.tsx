"use client";

import { useSearchParams } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import Link from "next/link";
import { AlertTriangle } from "lucide-react";

const ERROR_MESSAGES: Record<string, string> = {
  Configuration: "There is a problem with the server configuration.",
  AccessDenied: "You do not have permission to sign in.",
  Verification: "The verification link has expired or is invalid.",
  Default: "An authentication error occurred.",
  CredentialsSignin:
    "Invalid credentials. Please check your hotkey and try again.",
  SessionRequired: "Please sign in to access this page.",
};

export default function AuthErrorPage() {
  const searchParams = useSearchParams();
  const error = searchParams.get("error") || "Default";
  const message = ERROR_MESSAGES[error] || ERROR_MESSAGES.Default;

  return (
    <div className="flex min-h-[60vh] items-center justify-center animate-fade-in">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-red-100">
            <AlertTriangle className="h-6 w-6 text-red-600" />
          </div>
          <CardTitle className="text-xl">Authentication Error</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4 text-center">
          <p className="text-sm text-gray-600">{message}</p>
          <div className="flex gap-3 justify-center">
            <Link href="/auth/signin">
              <Button>Try Again</Button>
            </Link>
            <Link href="/">
              <Button variant="outline">Go Home</Button>
            </Link>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
