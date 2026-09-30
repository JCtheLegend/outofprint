"use client";

import { useEffect } from "react";

/**
 * The last resort: shown when the root layout itself fails, so it replaces the
 * whole document and can't rely on the site's fonts or stylesheet — hence the
 * inline styles in the site's cream and ink.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#f5f0e8",
          color: "#1a1614",
          fontFamily: "Georgia, 'Times New Roman', serif",
          textAlign: "center",
          padding: "24px",
        }}
      >
        <div style={{ maxWidth: 480 }}>
          <p style={{ letterSpacing: "0.15em", textTransform: "uppercase", fontSize: 11, color: "#8b3a2a" }}>
            Out of Print Press
          </p>
          <h1 style={{ fontWeight: 400, fontSize: 32, margin: "12px 0" }}>Something went wrong</h1>
          <p style={{ fontSize: 14, lineHeight: 1.6, color: "#6b6560" }}>
            The site couldn&apos;t load just now. Please try again in a moment.
          </p>
          <p style={{ marginTop: 24 }}>
            <button
              type="button"
              onClick={reset}
              style={{
                background: "#8b3a2a",
                color: "#f5f0e8",
                border: 0,
                padding: "10px 20px",
                fontSize: 14,
                cursor: "pointer",
              }}
            >
              Try again
            </button>{" "}
            {/* A full reload, not client navigation: the app shell is what broke */}
            {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
            <a href="/" style={{ color: "#8b3a2a", fontSize: 14, marginLeft: 12 }}>
              Go to the home page
            </a>
          </p>
          {error.digest && (
            <p style={{ fontSize: 12, color: "#6b6560", marginTop: 32 }}>Reference: {error.digest}</p>
          )}
        </div>
      </body>
    </html>
  );
}
