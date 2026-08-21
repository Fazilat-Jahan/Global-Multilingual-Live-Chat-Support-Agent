import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Support Chat Widget",
  description: "Embeddable multilingual live chat support widget",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
