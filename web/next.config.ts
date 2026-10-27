import type { NextConfig } from "next";

/**
 * DO NOT SET `output: "export"`.
 *
 * Static export disables Route Handlers, which kills:
 *   - /api/run      (live mode; also the only thing keeping MODEL_API_KEY
 *                    out of the browser bundle)
 *   - /api/stream   (the commentary and MMIO trace streams)
 *
 * The keyless guarantee does not need static export: /replay/[chip] is a
 * statically rendered server component with generateStaticParams, so those
 * routes are prerendered at build time and served from the edge cache with
 * zero API calls. We get both halves on Vercel's standard runtime.
 *
 * Verify after `npm run build`: the replay routes must be listed as
 * prerendered (○ or ●), not dynamic (ƒ).
 */
const nextConfig: NextConfig = {
  reactStrictMode: true,

  // pdf.js ships a worker that must not be bundled for the server.
  serverExternalPackages: ["pdfjs-dist"],

  webpack: (config, { isServer }) => {
    if (!isServer) {
      // canvas is an optional pdf.js dependency only used under Node.
      config.resolve.fallback = { ...config.resolve.fallback, canvas: false };
    }
    return config;
  },
};

export default nextConfig;
