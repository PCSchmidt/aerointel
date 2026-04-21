/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  webpack: (config) => {
    // Prevent optional canvas dependency from causing SSR build errors.
    // Map component is loaded with dynamic({ ssr: false }) so canvas is
    // never required at build time, but webpack still tries to resolve it.
    config.resolve.fallback = {
      ...config.resolve.fallback,
      canvas: false,
    };
    return config;
  },
};

module.exports = nextConfig;
