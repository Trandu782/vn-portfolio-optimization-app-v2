"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import { DataFreshnessBadge } from "@/components/DataFreshnessBadge";
import { BrandMark, MenuIcon, XIcon } from "@/components/ui/Icons";

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
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <header className="sticky top-0 z-30 border-b border-hairline bg-page/90 pt-[env(safe-area-inset-top)] backdrop-blur-sm">
      <nav
        aria-label="Primary"
        className="mx-auto flex h-14 max-w-[1440px] items-center justify-between gap-4 px-4 sm:px-6 lg:px-8"
      >
        <div className="flex items-center gap-6">
          <Link
            href="/"
            onClick={() => setMobileOpen(false)}
            className="inline-flex items-center gap-2 whitespace-nowrap text-[15px] font-medium text-fg transition-colors duration-150 ease-unslop hover:text-fg-secondary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-page rounded-md"
          >
            <BrandMark size={16} className="text-fg" />
            <span>VN Portfolio Optimizer</span>
          </Link>

          <ul className="hidden md:flex md:items-center md:gap-1">
            {links.map((link) => {
              const active =
                pathname === link.href || pathname.startsWith(`${link.href}/`);
              return (
                <li key={link.href}>
                  <Link
                    href={link.href}
                    aria-current={active ? "page" : undefined}
                    className={`inline-flex h-9 items-center rounded-md px-3 text-sm whitespace-nowrap transition-colors duration-150 ease-unslop focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-page ${
                      active
                        ? "bg-raised font-medium text-fg"
                        : "text-fg-secondary hover:bg-raised/60 hover:text-fg"
                    }`}
                  >
                    {link.label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>

        <div className="flex items-center gap-2">
          <div className="hidden sm:block">
            <DataFreshnessBadge />
          </div>
          <button
            type="button"
            onClick={() => setMobileOpen((prev) => !prev)}
            aria-expanded={mobileOpen}
            aria-controls="mobile-nav-menu"
            aria-label={mobileOpen ? "Close navigation menu" : "Open navigation menu"}
            className="inline-flex h-11 w-11 items-center justify-center rounded-lg border border-hairline bg-surface text-fg-secondary transition-colors duration-150 ease-unslop hover:bg-raised hover:text-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent md:hidden"
          >
            {mobileOpen ? <XIcon size={18} /> : <MenuIcon size={18} />}
          </button>
        </div>
      </nav>

      {mobileOpen && (
        <div
          id="mobile-nav-menu"
          className="border-t border-hairline bg-page px-4 py-3 sm:px-6 md:hidden"
        >
          <ul className="space-y-1">
            {links.map((link) => {
              const active =
                pathname === link.href || pathname.startsWith(`${link.href}/`);
              return (
                <li key={link.href}>
                  <Link
                    href={link.href}
                    onClick={() => setMobileOpen(false)}
                    aria-current={active ? "page" : undefined}
                    className={`flex min-h-[44px] items-center rounded-lg px-3 text-sm transition-colors duration-150 ease-unslop ${
                      active
                        ? "bg-raised font-medium text-fg"
                        : "text-fg-secondary hover:bg-raised/60 hover:text-fg"
                    }`}
                  >
                    {link.label}
                  </Link>
                </li>
              );
            })}
          </ul>
          <div className="mt-3 border-t border-hairline pt-3 sm:hidden">
            <DataFreshnessBadge />
          </div>
        </div>
      )}
    </header>
  );
}
