/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  env: {
    // In production nginx proxies /client/ and /admin/ so relative paths work.
    // In dev each dashboard runs on its own port — set these in .env.local:
    //   NEXT_PUBLIC_CLIENT_URL=http://localhost:3001/client
    //   NEXT_PUBLIC_ADMIN_URL=http://localhost:3002/admin
    NEXT_PUBLIC_CLIENT_URL: process.env.NEXT_PUBLIC_CLIENT_URL || "/client",
    NEXT_PUBLIC_ADMIN_URL: process.env.NEXT_PUBLIC_ADMIN_URL || "/admin",
  },
};

module.exports = nextConfig;
