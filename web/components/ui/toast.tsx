"use client";

import {
  useEffect,
  useState,
  useCallback,
  createContext,
  useContext,
} from "react";
import { X } from "lucide-react";

type ToastVariant = "default" | "success" | "error";

interface Toast {
  id: number;
  message: string;
  variant: ToastVariant;
}

interface ToastContextValue {
  toast: (message: string, variant?: ToastVariant) => void;
}

const ToastContext = createContext<ToastContextValue>({
  toast: () => {},
});

export function useToast() {
  return useContext(ToastContext);
}

let nextId = 0;

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const toast = useCallback(
    (message: string, variant: ToastVariant = "default") => {
      const id = ++nextId;
      setToasts((prev) => [...prev, { id, message, variant }]);
    },
    [],
  );

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm">
        {toasts.map((t) => (
          <ToastItem key={t.id} toast={t} onDismiss={dismiss} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

function ToastItem({
  toast,
  onDismiss,
}: {
  toast: Toast;
  onDismiss: (id: number) => void;
}) {
  useEffect(() => {
    const timer = setTimeout(() => onDismiss(toast.id), 5000);
    return () => clearTimeout(timer);
  }, [toast.id, onDismiss]);

  const bg =
    toast.variant === "error"
      ? "bg-red-600 text-white"
      : toast.variant === "success"
        ? "bg-green-600 text-white"
        : "bg-zinc-800 text-zinc-100";

  return (
    <div
      className={`${bg} rounded-lg px-4 py-3 shadow-lg flex items-center gap-2 animate-in slide-in-from-right-5`}
    >
      <span className="flex-1 text-sm">{toast.message}</span>
      <button
        onClick={() => onDismiss(toast.id)}
        className="shrink-0 opacity-70 hover:opacity-100"
        aria-label="Dismiss"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}
