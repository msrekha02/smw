import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";

/**
 * The shell every route shares: fonts, the session provider, nothing else.
 *
 * The authenticated chrome (nav, guard, footer) lives in `(app)/layout.tsx`
 * rather than here, because the marketing page at `/` has to render with no
 * session and with a nav of its own. Keeping the chrome one level down is what
 * lets a public page and a guarded page share a session provider without
 * sharing a header.
 */
export const metadata: Metadata = {
  title: "Smart Market Watchlist",
  description: "A watchlist that gets quieter as it gets smarter.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen selection:bg-brand selection:text-white">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
