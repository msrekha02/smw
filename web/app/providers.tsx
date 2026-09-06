"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { AuthProvider } from "@/lib/auth";
import { installArmListeners, installFlushListeners } from "@/lib/receipts";

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: 1,
            refetchOnWindowFocus: true,
            staleTime: 10_000,
          },
        },
      }),
  );

  useEffect(() => {
    const disarm = installArmListeners();
    const stopFlush = installFlushListeners();
    return () => {
      disarm();
      stopFlush();
    };
  }, []);

  return (
    <QueryClientProvider client={client}>
      <AuthProvider>{children}</AuthProvider>
    </QueryClientProvider>
  );
}
