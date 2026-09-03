import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

import { SESSION_COOKIE } from '@/lib/session'

/**
 * Unit 20a (MEADOWOPS-UI-002): presence-only auth gate, same shape as
 * orbynadmin's own proxy/middleware (Unit 8/17a) — the Edge runtime this
 * middleware executes in can't verify the signed session token, so a
 * forged/stale cookie still gets past this check. Every actual data
 * request goes through src/lib/scenario-api.ts, which forwards it to the
 * backend for real verification, and every authenticated page load also
 * re-checks the role server-side in (dashboard)/layout.tsx — this
 * middleware only avoids flashing an empty authenticated shell before
 * that check runs.
 */
export function middleware(request: NextRequest) {
  // /login is not a real route in this template — redirect to the actual sign-in page.
  if (request.nextUrl.pathname === '/login') {
    return NextResponse.redirect(new URL('/sign-in', request.url))
  }

  const isAuthed = Boolean(request.cookies.get(SESSION_COOKIE)?.value)
  const { pathname } = request.nextUrl

  if (!isAuthed && pathname !== '/sign-in') {
    return NextResponse.redirect(new URL('/sign-in', request.url))
  }

  if (isAuthed && pathname === '/sign-in') {
    return NextResponse.redirect(new URL('/dashboard', request.url))
  }

  return NextResponse.next()
}

// See "Matching Paths" below to learn more
export const config = {
  matcher: [
    // Match all request paths except for the ones starting with:
    // - api (API routes)
    // - _next/static (static files)
    // - _next/image (image optimization files)
    // - favicon.ico (favicon file)
    '/((?!api|_next/static|_next/image|favicon.ico).*)',
  ],
}
