import type { Metadata } from "next";
import { Manrope, Cormorant_Garamond, JetBrains_Mono } from "next/font/google";
import "./globals.css";

const manrope = Manrope({
  subsets: ["latin"],
  variable: "--font-sans",
  weight: ["300", "400", "500", "600", "700"],
});

const cormorant = Cormorant_Garamond({
  subsets: ["latin"],
  variable: "--font-display",
  weight: ["300", "400", "600"],
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  weight: ["300", "400", "500", "700"],
});

export const metadata: Metadata = {
  title: "AeroIntel — Real-Time Aviation Intelligence",
  description:
    "Kalman filtering, DBSCAN pattern detection, and LLM-powered analysis on live ADS-B telemetry. By Chris Schmidt.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${manrope.variable} ${cormorant.variable} ${jetbrainsMono.variable}`}>
      <body className="bg-[#0a0c0f] overflow-hidden">{children}</body>
    </html>
  );
}
