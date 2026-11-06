import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "FinAlly",
  description: "AI trading workstation: live NSE prices, simulated trading, and an AI copilot.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="bg-bg font-mono text-ink antialiased">{children}</body>
    </html>
  );
}
