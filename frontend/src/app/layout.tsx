import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import { Providers } from "./providers";
import "@/styles/globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });

export const metadata: Metadata = {
  title: { default: "Scrum Bot", template: "%s · Scrum Bot" },
  description: "AI standups for Microsoft Teams — reports, blockers and team health.",
};

export const viewport: Viewport = {
  // Browser chrome color must be a literal; matches --bg in tokens.css.
  // eslint-disable-next-line no-restricted-syntax
  themeColor: "#f4f6f8",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={inter.variable}>
      <body className="min-h-screen bg-bg font-sans text-fg">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
