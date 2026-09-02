import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  devIndicators: false,

  // Unit 8 security review: this app is now cookie-authenticated (the
  // Builder session cookie, src/lib/session.ts) and serves the admin
  // master-data CRUD panel — it had no response headers configured at all.
  // Matches the sibling Subsystem 2 template's header set (web/security.md)
  // plus HSTS/Permissions-Policy. No CSP here yet — Next.js's own hydration
  // scripts need either 'unsafe-inline' or per-request nonces, and wiring
  // nonces is a larger change than this fix; tracked as follow-up.
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          {
            key: "Strict-Transport-Security",
            value: "max-age=31536000; includeSubDomains; preload",
          },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=()",
          },
        ],
      },
    ];
  },
};

export default nextConfig;
