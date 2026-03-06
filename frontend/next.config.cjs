/** @type {import('next').NextConfig} */
const nextConfig = {
  // Enable standalone output for Docker production builds
  // This creates a minimal standalone folder that includes only necessary files
  output: 'standalone',

  // Disable x-powered-by header for security
  poweredByHeader: false,

  // Enable strict mode for catching potential problems
  reactStrictMode: true,

  // Environment variables available at build time
  // Runtime variables should use NEXT_PUBLIC_ prefix
  env: {
    // Add any build-time environment variables here
  },

  // Image optimization settings
  images: {
    // Disable image optimization in standalone mode
    // (can be re-enabled if using a separate image optimization service)
    unoptimized: true,
  },
};

module.exports = nextConfig;
