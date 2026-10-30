/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  // Uploads go through the proxy route; allow large multipart bodies.
  experimental: { serverActions: { bodySizeLimit: "60mb" } },
};

export default nextConfig;
