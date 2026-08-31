import Link from "next/link";

const FOOTER_LINKS = [
  {
    label: "Product",
    items: [
      { label: "Features", href: "#features" },
      { label: "How it works", href: "#how-it-works" },
      { label: "Pricing", href: "#pricing" },
    ],
  },
  {
    label: "Platform",
    items: [
      { label: "Client login", href: "/login" },
      { label: "Admin login", href: "/admin/" },
      { label: "Status", href: "#" },
    ],
  },
  {
    label: "Company",
    items: [
      { label: "Contact", href: "#contact" },
      { label: "Privacy policy", href: "#" },
      { label: "Terms of service", href: "#" },
    ],
  },
];

export function Footer() {
  return (
    <footer className="border-t border-mist bg-ash">
      <div className="mx-auto max-w-site px-6 py-16">
        <div className="grid grid-cols-1 gap-12 lg:grid-cols-4">

          {/* Brand column */}
          <div className="lg:col-span-1">
            <Link
              href="/"
              className="font-display text-base font-normal tracking-display text-graphite"
            >
              StayKaro
            </Link>
            <p className="mt-4 font-body text-sm leading-relaxed text-steel">
              AI calling agent built for hospitality teams. Automate outbound
              calls, capture transcripts, and keep your guests informed.
            </p>
            <a
              href="mailto:staykaro26@gmail.com"
              className="mt-4 block font-body text-sm link-ember text-graphite"
            >
              staykaro26@gmail.com
            </a>
          </div>

          {/* Link columns */}
          {FOOTER_LINKS.map((col) => (
            <div key={col.label}>
              <p className="mb-4 font-body text-xs uppercase tracking-widest text-slate">
                {col.label}
              </p>
              <ul className="space-y-3">
                {col.items.map((item) => (
                  <li key={item.label}>
                    <Link
                      href={item.href}
                      className="font-body text-sm text-steel transition-colors hover:text-graphite"
                    >
                      {item.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="mt-16 flex flex-col items-start justify-between gap-4 border-t border-mist pt-8 lg:flex-row lg:items-center">
          <p className="font-body text-xs text-slate">
            &copy; {new Date().getFullYear()} StayKaro. All rights reserved.
          </p>
          <p className="font-display text-xs font-normal tracking-display text-slate">
            India &middot; UAE &middot; Global
          </p>
        </div>
      </div>
    </footer>
  );
}
