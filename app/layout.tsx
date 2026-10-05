import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Spread — an example bot on uselayer",
  description: "Best venue and cross-venue arbitrage across Kalshi and Polymarket US, run on your machine with your own keys.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
