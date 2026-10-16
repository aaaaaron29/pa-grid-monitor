import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { Nav } from "@/components/Nav";
import { SnapshotBanner } from "@/components/SnapshotBanner";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

// Every route here reads live Postgres data on every request; there's no meaningful
// static shell to prerender, so opt the whole app out of Cache Components' static-shell
// requirement instead of adding Suspense boundaries purely to satisfy it.
export const instant = false;

export const metadata: Metadata = {
  title: "Grid Watch",
  description: "Real-time PJM grid anomaly detection and a data-center accountability case study.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      data-scroll-behavior="smooth"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <SnapshotBanner />
        <Nav />
        {children}
      </body>
    </html>
  );
}
