/** @type {import('next').NextConfig} */

// Spec 5.1: restrict which sites can embed the widget iframe via CSP
// frame-ancestors (the modern replacement for X-Frame-Options ALLOWFROM,
// which no modern browser implements). Default embedder list matches the
// local dev frontend; production must set WIDGET_ALLOWED_EMBEDDERS to the
// client website domain(s). 'self' is always included so the widget page
// can be loaded from the widget host itself (our own demos).
const embedders = (process.env.WIDGET_ALLOWED_EMBEDDERS || "http://localhost:3000")
  .split(",")
  .map((s) => s.trim())
  .filter(Boolean);
const frameAncestors = ["'self'", ...embedders].join(" ");

const nextConfig = {
  reactStrictMode: true,
  async headers() {
    return [
      {
        source: "/widget",
        headers: [{ key: "Content-Security-Policy", value: `frame-ancestors ${frameAncestors}` }],
      },
      {
        source: "/widget/:path*",
        headers: [{ key: "Content-Security-Policy", value: `frame-ancestors ${frameAncestors}` }],
      },
    ];
  },
};

export default nextConfig;
