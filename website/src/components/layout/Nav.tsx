"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import Image from "next/image";
import { usePathname } from "next/navigation";
import logo from "@/public/ooplogo_black.png";
import { useCart } from "@/components/cart/CartProvider";

const links = [
  { href: "/", label: "Home" },
  { href: "/catalog", label: "Catalog" },
  { href: "/submit", label: "Submit a Book" },
];

const linkBase =
  "font-body text-xs tracking-widest uppercase transition-colors border-b-[1.5px]";

function linkClasses(active: boolean): string {
  return `${linkBase} ${
    active
      ? "text-ink border-rust"
      : "text-muted border-transparent hover:text-ink hover:border-rust"
  }`;
}

export function Nav() {
  const pathname = usePathname();
  const { count, ready } = useCart();
  const [open, setOpen] = useState(false);

  // Following a link has served the menu's purpose
  useEffect(() => setOpen(false), [pathname]);

  const cartLabel = `Cart${ready && count > 0 ? ` (${count})` : ""}`;

  return (
    <nav className="sticky top-0 z-50 bg-cream border-b border-border">
      <div className="max-w-5xl mx-auto px-6 py-4 flex items-center justify-between gap-3">
        {/* Brand — allowed to shrink and truncate so it can never collide
            with the links beside it on a narrow screen */}
        <Link
          href="/"
          className="flex items-center gap-2 sm:gap-3 font-serif text-base sm:text-lg font-semibold tracking-wide min-w-0"
        >
          <Image
            src={logo}
            alt="Out of Print Press Logo"
            width={40}
            height={20}
            className="object-contain shrink-0"
          />
          <span className="truncate">
            <span className="text-rust italic">Out Of Print</span> Press
          </span>
        </Link>

        {/* Full navigation, once there is room for it */}
        <div className="hidden md:flex items-center gap-8">
          {links.map(({ href, label }) => (
            <Link key={href} href={href} className={`${linkClasses(pathname === href)} pb-0.5`}>
              {label}
            </Link>
          ))}
          <Link href="/cart" className={`${linkClasses(pathname === "/cart")} pb-0.5`}>
            {cartLabel}
          </Link>
        </div>

        {/* Narrow screens: the cart stays one tap away, the rest folds away */}
        <div className="flex md:hidden items-center gap-4 shrink-0">
          <Link href="/cart" className={`${linkClasses(pathname === "/cart")} pb-0.5`}>
            {cartLabel}
          </Link>
          <button
            type="button"
            onClick={() => setOpen((isOpen) => !isOpen)}
            aria-label={open ? "Close menu" : "Open menu"}
            aria-expanded={open}
            aria-controls="mobile-nav"
            className="p-1 -mr-1 text-ink cursor-pointer"
          >
            <svg width="22" height="22" viewBox="0 0 22 22" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
              {open ? (
                <>
                  <line x1="5" y1="5" x2="17" y2="17" />
                  <line x1="17" y1="5" x2="5" y2="17" />
                </>
              ) : (
                <>
                  <line x1="3" y1="6" x2="19" y2="6" />
                  <line x1="3" y1="11" x2="19" y2="11" />
                  <line x1="3" y1="16" x2="19" y2="16" />
                </>
              )}
            </svg>
          </button>
        </div>
      </div>

      {open && (
        <div id="mobile-nav" className="md:hidden border-t border-border">
          <div className="max-w-5xl mx-auto px-6 flex flex-col">
            {links.map(({ href, label }) => (
              <Link
                key={href}
                href={href}
                className={`${linkClasses(pathname === href)} border-b-0 py-4 border-t border-border/50 first:border-t-0`}
              >
                {label}
              </Link>
            ))}
          </div>
        </div>
      )}
    </nav>
  );
}
