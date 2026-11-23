"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { DataFreshnessBadge } from "@/components/DataFreshnessBadge";

const links = [
  { href: "/portfolio", label: "Portfolio" },
  { href: "/pnl", label: "P&L" },
  { href: "/optimize", label: "Optimize" },
  { href: "/sector", label: "Sector" },
  { href: "/risk", label: "Risk" },
  { href: "/rebalance", label: "Rebalance" },
  { href: "/settings", label: "Settings" },
];

export function Nav() {
  const pathname = usePathname();

  return (
    <header className="border-b border-gray-200 dark:border-gray-800">
      <nav className="mx-auto flex max-w-5xl flex-wrap items-center gap-6 px-6 py-4">
        <Link href="/" className="text-base font-semibold">
          VN Portfolio Optimizer
        </Link>
        <ul className="flex flex-1 flex-wrap gap-4 text-sm">
          {links.map((link) => {
            const active =
              pathname === link.href || pathname.startsWith(`${link.href}/`);
            return (
              <li key={link.href}>
                <Link
                  href={link.href}
                  aria-current={active ? "page" : undefined}
                  className={
                    active
                      ? "font-medium text-blue-600 dark:text-blue-400"
                      : "text-gray-600 hover:text-gray-900 dark:text-gray-300 dark:hover:text-white"
                  }
                >
                  {link.label}
                </Link>
              </li>
            );
          })}
        </ul>
        <DataFreshnessBadge />
      </nav>
    </header>
  );
}