import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "INSTAGRAM RESOLVER // DOWNLOADER",
  description: "High-performance clinical utility to resolve and stream Instagram single-media or carousel posts.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased">
        {children}
      </body>
    </html>
  );
}
