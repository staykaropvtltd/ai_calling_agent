import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "StayKaro — AI Calling Agent for Hotels",
  description:
    "Automate guest communication with an AI voice agent. Outbound calls, real-time transcripts, and customer intelligence for hospitality teams.",
  keywords: ["AI calling", "hotel automation", "voice agent", "hospitality AI", "outbound calls"],
  openGraph: {
    title: "StayKaro — AI Calling Agent for Hotels",
    description: "Automate guest communication with an AI voice agent built for hospitality.",
    type: "website",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-canvas text-graphite font-body">{children}</body>
    </html>
  );
}
