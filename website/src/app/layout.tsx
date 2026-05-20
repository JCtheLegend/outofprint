import type { Metadata } from "next";
import { Playfair_Display, Lora } from "next/font/google";
import "./globals.css";
import { Nav } from "@/components/layout/Nav";

const playfair = Playfair_Display({
  subsets: ["latin"],
  variable: "--font-playfair",
  display: "swap",
});

const lora = Lora({
  subsets: ["latin"],
  variable: "--font-lora",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Out of Print Press",
  description:
    "We restore and reprint out-of-circulation books. Request a lost title or purchase a physical copy of a book we've already revived.",
  openGraph: {
    title: "Out of Print Press",
    description: "Forgotten books, revived.",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`${playfair.variable} ${lora.variable}`}>
      <body className="bg-cream text-ink font-body antialiased">
        <Nav />
        <main>{children}</main>
        <footer className="border-t border-border mt-16 py-8 text-center text-muted text-sm">
          <p>© {new Date().getFullYear()} Out of Print Press. Preserving literature, one book at a time.</p>
        </footer>
      </body>
    </html>
  );
}
