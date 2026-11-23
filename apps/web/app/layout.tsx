import type { Metadata } from "next";
import type { ReactNode } from "react";

import { Footer } from "@/components/Footer";
import { Nav } from "@/components/Nav";
import { AppStoreProvider } from "@/lib/app-store-context";

import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "VN Portfolio Optimizer",
    template: "%s | VN Portfolio Optimizer",
  },
  description:
    "Portfolio optimization for Vietnamese equities. Decision support only, not financial advice.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body className="flex min-h-screen flex-col bg-white text-gray-900 antialiased dark:bg-gray-950 dark:text-gray-100">
        <AppStoreProvider>
          <Nav />
          <main className="mx-auto w-full max-w-5xl flex-1 px-6 py-8">{children}</main>
          <Footer />
        </AppStoreProvider>
      </body>
    </html>
  );
}
