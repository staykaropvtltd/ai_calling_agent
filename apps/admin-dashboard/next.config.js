/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  basePath: "/admin",
  // Canonicalize to a trailing slash so nginx's `location /admin/` (a safe
  // prefix match that can't accidentally swallow some future /adminfoo
  // route) and Next's own redirect agree on one canonical form. Without
  // this, Next strips the trailing slash while nginx's bare-vs-slash
  // handling redirects the other way — confirmed by hand as an actual
  // infinite 301/308 loop on `/admin` before this was set.
  trailingSlash: true,
  reactStrictMode: true,
};

module.exports = nextConfig;
