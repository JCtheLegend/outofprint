/** @type {import('next').NextConfig} */
const nextConfig = {
  // Required for Cloudflare Pages via @opennextjs/cloudflare
  // This tells Next.js to output in a format Cloudflare can run
  images: {
    // Cloudflare doesn't run next/image's built-in optimizer server-side.
    // Use "unoptimized" here and rely on Cloudflare's own Image Resizing
    // (available on Pro/Business plans), or a service like Cloudinary.
    unoptimized: true,
    remotePatterns: [
      {
        protocol: "https",
        hostname: "*.supabase.co",
        pathname: "/storage/v1/object/public/**",
      },
    ],
  },
};
 
module.exports = nextConfig;