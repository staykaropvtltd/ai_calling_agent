"use client";

import Link from "next/link";
import { useState } from "react";

const NAV_LINKS = [
  { label: "Features", href: "#features" },
  { label: "How it works", href: "#how-it-works" },
  { label: "Pricing", href: "#pricing" },
  { label: "Contact", href: "#contact" },
];

export function Nav() {
  const [open, setOpen] = useState(false);

  return (
    <header className="sticky top-0 z-50 border-b border-mist bg-canvas/95 backdrop-blur-sm">
      <div className="mx-auto flex max-w-site items-center justify-between px-6 py-4">

        {/* Brand */}
        <Link
          href="/"
          className="font-display text-base font-normal tracking-display text-graphite"
        >
          StayKaro
        </Link>

        {/* Desktop nav — pill container */}
        <nav className="hidden items-center gap-0 rounded-full bg-ash px-2 py-2 lg:flex">
          {NAV_LINKS.map((link) => (
            <a
              key={link.label}
              href={link.href}
              className="rounded-full px-5 py-2 font-display text-sm font-normal tracking-display text-graphite transition-colors hover:bg-canvas"
            >
              {link.label}
            </a>
          ))}
        </nav>

        {/* Desktop right — login */}
        <div className="hidden items-center gap-3 lg:flex">
          <Link
            href="/login"
            className="font-display text-sm font-normal tracking-display text-slate transition-colors hover:text-graphite"
          >
            Sign in
          </Link>
          <Link
            href="/login"
            className="bg-graphite px-4 py-2 font-display text-sm font-normal tracking-display text-canvas transition-colors hover:bg-steel"
          >
            Get started
          </Link>
        </div>

        {/* Mobile hamburger */}
        <button
          type="button"
          className="lg:hidden p-2 text-graphite"
          onClick={() => setOpen((v) => !v)}
          aria-label="Toggle menu"
        >
          <div className="space-y-1">
            <span className={`block h-px w-5 bg-graphite transition-all ${open ? "translate-y-1.5 rotate-45" : ""}`} />
            <span className={`block h-px w-5 bg-graphite transition-all ${open ? "opacity-0" : ""}`} />
            <span className={`block h-px w-5 bg-graphite transition-all ${open ? "-translate-y-1.5 -rotate-45" : ""}`} />
          </div>
        </button>
      </div>

      {/* Mobile menu */}
      {open && (
        <div className="border-t border-mist bg-canvas px-6 pb-6 lg:hidden">
          <nav className="flex flex-col gap-2 pt-4">
            {NAV_LINKS.map((link) => (
              <a
                key={link.label}
                href={link.href}
                className="font-display text-sm font-normal tracking-display text-graphite py-2 transition-colors hover:text-steel"
                onClick={() => setOpen(false)}
              >
                {link.label}
              </a>
            ))}
          </nav>
          <div className="mt-6 flex flex-col gap-3">
            <Link
              href="/login"
              className="text-center font-display text-sm font-normal tracking-display text-slate border border-mist py-2.5 transition-colors hover:border-steel"
            >
              Sign in
            </Link>
            <Link
              href="/login"
              className="text-center bg-graphite py-2.5 font-display text-sm font-normal tracking-display text-canvas transition-colors hover:bg-steel"
            >
              Get started
            </Link>
          </div>
        </div>
      )}
    </header>
  );
}
