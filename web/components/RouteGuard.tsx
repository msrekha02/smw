"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "@/lib/auth";
import { Skeleton } from "./ui";

/**
 * Reachable without a token.
 *
 * `/calibration` is here because it holds no user data: the alert rates are a
 * replay of stored bars through the production scorer, and precision@critical
 * aggregates every vote in the system rather than yours. It is also the
 * strongest evidence the project has, so putting it behind a sign-in hides the
 * one page that proves the claim.
 *
 * `/` is not listed because the landing page lives outside this group entirely
 * and never reaches the guard.
 */
const PUBLIC = new Set(["/login", "/calibration"]);

/** The only public page a signed-in user is sent away from. */
const ANON_ONLY = new Set(["/login"]);

/**
 * One gate for every route.
 *
 * Put here rather than in each page so a new page is protected by existing
 * rather than by remembering to add a check. `replace` rather than `push`: a
 * bounced navigation should not sit in the back button.
 */
export function RouteGuard({ children }: { children: React.ReactNode }) {
  const { status } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const isPublic = PUBLIC.has(pathname);

  // A signed-in user is bounced off the sign-in page and nowhere else. Bouncing
  // them off every public page would take someone who deliberately navigated to
  // the calibration data and send them somewhere they did not ask for.
  useEffect(() => {
    if (status === "anon" && !isPublic) router.replace("/login");
    if (status === "authed" && ANON_ONLY.has(pathname)) router.replace("/digest");
  }, [status, isPublic, pathname, router]);

  // While the token is being checked, and during the frame between deciding to
  // redirect and arriving, show the shape of the page rather than its contents.
  const settled =
    status === "loading"
      ? false
      : isPublic
        ? !(status === "authed" && ANON_ONLY.has(pathname))
        : status === "authed";

  if (!settled) {
    return (
      <div className="space-y-3" aria-busy="true">
        <Skeleton className="h-9 w-64" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  }

  return <>{children}</>;
}
