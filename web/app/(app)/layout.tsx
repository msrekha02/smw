import { Nav } from "@/components/Nav";
import { RouteGuard } from "@/components/RouteGuard";
import { ErrorBoundary } from "@/components/ui";

/**
 * The application shell.
 *
 * Everything under this group is a page you reach from the product nav, so the
 * guard sits here once rather than in each page: a new route is protected by
 * existing rather than by remembering to add a check. The route group adds no
 * path segment, so `/digest` is still `/digest`.
 */
export default function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen flex-col">
      <Nav />

      <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col px-5 py-10">
        <RouteGuard>
          <ErrorBoundary>{children}</ErrorBoundary>
        </RouteGuard>
      </main>

      <footer className="mx-auto w-full max-w-5xl border-t border-ink-line px-5 py-8 text-xs text-faint">
        <div className="flex flex-col items-center justify-between gap-4 md:flex-row">
          <span className="font-medium tracking-wide">
            &copy; {new Date().getFullYear()} Smart Market Watchlist
          </span>
        </div>
      </footer>
    </div>
  );
}
