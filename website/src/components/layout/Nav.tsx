"use client";

import Link from "next/link";
import Image from "next/image";
import { usePathname } from "next/navigation";
import logo from "@/public/ooplogo_black.png";

const links = [
  { href: "/", label: "Home" },
  { href: "/catalog", label: "Catalog" },
  { href: "/submit", label: "Submit a Book" },
];

export function Nav() {
  const pathname = usePathname();

  return (
    <nav className="sticky top-0 z-50 bg-cream border-b border-border">
      <div className="max-w-5xl mx-auto px-6 py-4 flex items-center justify-between">
        <Link href="/" className="flex items-center gap-3 font-serif text-lg font-semibold tracking-wide">
          <Image
            src={logo}
            alt="Out of Print Press Logo"
            width={40}
            height={20}
            className="object-contain"
          />
        <span className="text-rust italic">Out Of Print</span> Press
        </Link>
        <div className="flex items-center gap-8">
          {links.map(({ href, label }) => (
            <Link
              key={href}
              href={href}
              className={`font-body text-xs tracking-widest uppercase transition-colors pb-0.5 border-b-[1.5px] ${
                pathname === href
                  ? "text-ink border-rust"
                  : "text-muted border-transparent hover:text-ink hover:border-rust"
              }`}
            >
              {label}
            </Link>
          ))}
        </div>
      </div>
    </nav>
  );
}
