import type { NextConfig } from "next";

// Server-side proxy target for relative /api/* calls. In docker-compose the
// backend is a sibling service, so the frontend container must be given
// BACKEND_INTERNAL_URL=http://backend:8000; local dev falls back to localhost.
const backendInternalUrl =
  process.env.BACKEND_INTERNAL_URL || "http://localhost:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${backendInternalUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
