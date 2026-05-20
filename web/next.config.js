/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Allow images from the broker QR generator (and future hosted avatars).
  images: {
    remotePatterns: [
      { protocol: "https", hostname: "api.qrserver.com" },
      { protocol: "https", hostname: "avatars.githubusercontent.com" },
    ],
  },
}
module.exports = nextConfig
