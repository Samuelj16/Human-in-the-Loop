import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emits a self-contained server bundle for the Docker image in
  // docker-compose.yml. Vercel ignores this and builds its own way.
  output: "standalone",
};

export default nextConfig;
