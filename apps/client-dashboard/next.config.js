/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  basePath: "/client",
  // Canonicalize to a trailing slash so nginx's `location /client/` and
  // Next's own redirect agree on one canonical form — mirrors
  // apps/admin-dashboard/next.config.js, which hit an actual infinite
  // 301/308 loop on the bare basePath without this set.
  trailingSlash: true,
  reactStrictMode: true,
};

module.exports = nextConfig;
