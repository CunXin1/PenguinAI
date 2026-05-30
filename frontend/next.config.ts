import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",   // required for Docker multi-stage build
  experimental: {
    // enable when ready for partial prerendering
  },
  images: {
    remotePatterns: [],
  },
};

export default nextConfig;
