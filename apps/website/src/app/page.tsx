import Link from "next/link";
import { Nav } from "../components/Nav";
import { Footer } from "../components/Footer";

// ── Static data ───────────────────────────────────────────────────────────────

const STATS = [
  { value: "89%", label: "Answer rate" },
  { value: "4.2×", label: "More calls per hour" },
  { value: "340h", label: "Staff hours saved monthly" },
  { value: "12s", label: "Avg. first response time" },
];

const FEATURES = [
  {
    icon: "◎",
    title: "Natural AI conversations",
    body: "The AI speaks, listens, and responds in real time — in English, Hindi, Arabic, or the language your guests prefer. No robotic scripts. No dead air.",
  },
  {
    icon: "◈",
    title: "Real-time transcripts",
    body: "Every word of every call is captured automatically. Search, filter, and review conversations across all your properties from one dashboard.",
  },
  {
    icon: "◇",
    title: "Customer intelligence",
    body: "Build rich guest profiles from call data. Booking preferences, follow-up history, communication language — all linked to a single contact record.",
  },
  {
    icon: "◻",
    title: "Campaign calling",
    body: "Upload a contact list, configure the AI agent, and let it work through hundreds of calls overnight. Each result lands in your dashboard with a full summary.",
  },
  {
    icon: "◑",
    title: "Human escalation",
    body: "When the AI hits a situation that needs a person — complaints, negotiations, VIP requests — it hands off cleanly to your team with full call context.",
  },
  {
    icon: "◐",
    title: "Calendar & CRM integration",
    body: "StayKaro connects to Google Calendar, Microsoft Calendar, and your existing CRM. The AI can check availability, confirm appointments, and write back results.",
  },
];

const HOW_IT_WORKS = [
  {
    step: "01",
    title: "Upload your contacts",
    body: "Import a CSV or Excel sheet, or sync from your PMS. StayKaro validates phone numbers and deduplicates contacts automatically.",
  },
  {
    step: "02",
    title: "Configure the AI agent",
    body: "Tell the agent what to say, what to collect, and what actions it can take. Calling hours, fallback behaviour, and escalation rules — all configurable.",
  },
  {
    step: "03",
    title: "Start the campaign",
    body: "The queue runs automatically. Each call is dialled, conducted, and recorded. Failed calls are retried based on your retry policy.",
  },
  {
    step: "04",
    title: "Review and act",
    body: "Every completed call lands in your dashboard with a full transcript, AI summary, and extracted data. Your team focuses only on calls that need them.",
  },
];

const PRICING = [
  {
    name: "Starter",
    price: "₹8,000",
    period: "/month",
    description: "For a single property testing AI calling.",
    features: [
      "Up to 500 calls/month",
      "1 AI agent",
      "Call transcripts",
      "Basic analytics",
      "Email support",
    ],
    cta: "Get started",
    highlight: false,
  },
  {
    name: "Pro",
    price: "₹15,000",
    period: "/month",
    description: "For growing hotel teams with higher call volumes.",
    features: [
      "Up to 2,000 calls/month",
      "3 AI agents",
      "Full call transcripts + summaries",
      "Customer profiles",
      "Campaign calling",
      "Calendar integration",
      "Priority support",
    ],
    cta: "Start free trial",
    highlight: true,
  },
  {
    name: "Enterprise",
    price: "Custom",
    period: "",
    description: "For hotel groups, chains, and OTA platforms.",
    features: [
      "Unlimited calls",
      "Unlimited agents",
      "Custom AI instructions",
      "CRM / PMS integration",
      "Dedicated account manager",
      "SLA guarantee",
      "White-label available",
    ],
    cta: "Talk to us",
    highlight: false,
  },
];

// ── Page ──────────────────────────────────────────────────────────────────────

export default function HomePage() {
  return (
    <>
      <Nav />

      {/* ── Hero ─────────────────────────────────────────────────────────── */}
      <section className="bg-canvas pt-24 pb-20 lg:pt-32 lg:pb-28">
        <div className="mx-auto max-w-site px-6">
          <div className="grid grid-cols-1 gap-12 lg:grid-cols-2 lg:gap-16 lg:items-center">

            {/* Left — copy */}
            <div>
              <p className="mb-4 font-body text-sm font-medium uppercase tracking-widest text-ember">
                AI Calling Agent for Hospitality
              </p>
              <h1 className="mb-6 font-display text-4xl font-normal leading-tight tracking-display text-graphite lg:text-5xl xl:text-display">
                The AI that answers your phone,
                <br className="hidden lg:block" /> so your staff{" "}
                <span className="link-ember">don&apos;t have to</span>.
              </h1>
              <p className="mb-10 max-w-lg font-body text-subheading leading-relaxed text-steel">
                StayKaro handles your outbound calls — booking confirmations, guest
                follow-ups, reservation reminders — while your team focuses on
                delivering exceptional service at the property.
              </p>
              <div className="flex flex-wrap items-center gap-4">
                <Link
                  href="/login"
                  className="inline-flex items-center gap-2 bg-graphite px-6 py-3 font-display text-base font-normal tracking-display text-canvas transition-colors hover:bg-steel"
                >
                  Start free trial
                </Link>
                <Link
                  href="#how-it-works"
                  className="inline-flex items-center gap-2 border border-graphite px-6 py-3 font-display text-base font-normal tracking-display text-graphite transition-colors hover:bg-ash"
                >
                  See how it works
                </Link>
              </div>
            </div>

            {/* Right — data cards */}
            <div className="relative lg:h-[480px]">
              <StatCluster />
            </div>
          </div>
        </div>
      </section>

      {/* ── Stats strip ──────────────────────────────────────────────────── */}
      <section className="border-y border-mist bg-ash">
        <div className="mx-auto max-w-site px-6 py-8">
          <div className="grid grid-cols-2 gap-8 lg:grid-cols-4">
            {STATS.map((s) => (
              <div key={s.label} className="text-center lg:text-left">
                <div className="font-display text-heading font-normal tracking-display text-graphite">
                  {s.value}
                </div>
                <div className="mt-1 font-body text-sm text-slate">{s.label}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Features ─────────────────────────────────────────────────────── */}
      <section className="section bg-canvas" id="features">
        <div className="mx-auto max-w-site px-6">
          <div className="mb-16 max-w-xl">
            <p className="mb-3 font-body text-sm font-medium uppercase tracking-widest text-brass">
              Capabilities
            </p>
            <h2 className="font-display text-heading font-normal tracking-display text-graphite lg:text-heading-lg">
              Everything a hospitality team needs from an AI calling agent
            </h2>
          </div>

          <div className="grid grid-cols-1 gap-px bg-mist md:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map((f) => (
              <div key={f.title} className="bg-canvas p-8">
                <div className="mb-4 font-display text-2xl text-ember">{f.icon}</div>
                <h3 className="mb-3 font-display text-subheading font-normal tracking-display text-graphite">
                  {f.title}
                </h3>
                <p className="font-body text-sm leading-relaxed text-steel">{f.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── How it works ─────────────────────────────────────────────────── */}
      <section className="section bg-ash" id="how-it-works">
        <div className="mx-auto max-w-site px-6">
          <div className="mb-16 max-w-xl">
            <p className="mb-3 font-body text-sm font-medium uppercase tracking-widest text-brass">
              Process
            </p>
            <h2 className="font-display text-heading font-normal tracking-display text-graphite lg:text-heading-lg">
              From contact list to completed calls in four steps
            </h2>
          </div>

          <div className="grid grid-cols-1 gap-8 md:grid-cols-2 lg:grid-cols-4">
            {HOW_IT_WORKS.map((step, i) => (
              <div key={step.step} className="relative">
                {/* Connector line */}
                {i < HOW_IT_WORKS.length - 1 && (
                  <div className="absolute top-5 left-12 hidden h-px w-full bg-mist lg:block" />
                )}
                <div className="relative">
                  <div className="mb-4 inline-flex h-10 w-10 items-center justify-center border border-mist bg-canvas">
                    <span className="font-display text-xs font-normal tracking-display text-slate">
                      {step.step}
                    </span>
                  </div>
                  <h3 className="mb-2 font-display text-base font-normal tracking-display text-graphite">
                    {step.title}
                  </h3>
                  <p className="font-body text-sm leading-relaxed text-steel">{step.body}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Featured asymmetric card ──────────────────────────────────────── */}
      <section className="section bg-canvas">
        <div className="mx-auto max-w-site px-6">
          <div className="grid grid-cols-1 gap-0 overflow-hidden lg:grid-cols-5">
            {/* Ivory asymmetric card */}
            <div
              className="bg-ivory px-16 py-20 lg:col-span-3"
              style={{ borderRadius: "6px 0px 0px 0px" }}
            >
              <p className="mb-4 font-body text-sm font-medium uppercase tracking-widest text-brass">
                The problem we solve
              </p>
              <h2 className="mb-6 font-display text-heading font-normal tracking-display text-graphite">
                A hotel front desk handles 200+ calls a day. Most of them are the
                same 12 questions.
              </h2>
              <p className="mb-8 font-body text-base leading-relaxed text-steel">
                Breakfast timings. Check-in hours. Parking. Restaurant reservations.
                Early check-out. Your staff are capable of far more — but they spend
                most of their shift repeating the same answers to the same callers.
                StayKaro takes the repetitive calls, so your team can focus on the
                guests standing in front of them.
              </p>
              <Link
                href="/login"
                className="inline-flex items-center gap-2 bg-graphite px-6 py-3 font-display text-base font-normal tracking-display text-canvas transition-colors hover:bg-steel"
              >
                Start free trial →
              </Link>
            </div>

            {/* Right — call sample card */}
            <div className="bg-graphite px-10 py-16 lg:col-span-2">
              <p className="mb-6 font-body text-xs uppercase tracking-widest text-white/40">
                Live call — in progress
              </p>
              <CallSample />
            </div>
          </div>
        </div>
      </section>

      {/* ── Pricing ──────────────────────────────────────────────────────── */}
      <section className="section bg-ash" id="pricing">
        <div className="mx-auto max-w-site px-6">
          <div className="mb-16 max-w-xl">
            <p className="mb-3 font-body text-sm font-medium uppercase tracking-widest text-brass">
              Pricing
            </p>
            <h2 className="font-display text-heading font-normal tracking-display text-graphite lg:text-heading-lg">
              Simple plans. No per-minute surprises.
            </h2>
          </div>

          <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
            {PRICING.map((plan) => (
              <div
                key={plan.name}
                className={`flex flex-col p-8 ${
                  plan.highlight
                    ? "bg-graphite text-canvas"
                    : "border border-mist bg-canvas"
                }`}
              >
                <div className="mb-6">
                  <div
                    className={`mb-1 font-display text-sm font-normal tracking-display uppercase ${
                      plan.highlight ? "text-white/50" : "text-slate"
                    }`}
                  >
                    {plan.name}
                  </div>
                  <div className="flex items-baseline gap-1">
                    <span
                      className={`font-display text-heading-lg font-normal tracking-display ${
                        plan.highlight ? "text-canvas" : "text-graphite"
                      }`}
                    >
                      {plan.price}
                    </span>
                    {plan.period && (
                      <span
                        className={`font-body text-sm ${
                          plan.highlight ? "text-white/50" : "text-slate"
                        }`}
                      >
                        {plan.period}
                      </span>
                    )}
                  </div>
                  <p
                    className={`mt-2 font-body text-sm ${
                      plan.highlight ? "text-white/60" : "text-steel"
                    }`}
                  >
                    {plan.description}
                  </p>
                </div>

                <ul className="mb-8 flex-1 space-y-3">
                  {plan.features.map((f) => (
                    <li
                      key={f}
                      className={`flex items-start gap-2.5 font-body text-sm ${
                        plan.highlight ? "text-white/80" : "text-steel"
                      }`}
                    >
                      <span className={plan.highlight ? "text-ember" : "text-ember"}>◎</span>
                      {f}
                    </li>
                  ))}
                </ul>

                <Link
                  href={plan.name === "Enterprise" ? "#contact" : "/login"}
                  className={`inline-flex items-center justify-center gap-2 px-6 py-3 font-display text-sm font-normal tracking-display transition-colors ${
                    plan.highlight
                      ? "bg-ember text-white hover:bg-[#e05520]"
                      : "border border-graphite bg-transparent text-graphite hover:bg-ash"
                  }`}
                >
                  {plan.cta}
                </Link>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Contact / CTA ────────────────────────────────────────────────── */}
      <section className="section bg-canvas" id="contact">
        <div className="mx-auto max-w-site px-6">
          <div className="grid grid-cols-1 gap-16 lg:grid-cols-2 lg:items-start">
            <div>
              <p className="mb-3 font-body text-sm font-medium uppercase tracking-widest text-brass">
                Get in touch
              </p>
              <h2 className="mb-6 font-display text-heading font-normal tracking-display text-graphite lg:text-heading-lg">
                Ready to reduce your call volume?
              </h2>
              <p className="mb-8 font-body text-base leading-relaxed text-steel">
                Most hotels see measurable reduction in repetitive front-desk calls
                within the first two weeks. Book a 20-minute demo and we&apos;ll
                walk through a configuration specific to your property.
              </p>
              <div className="flex flex-wrap gap-4">
                <Link
                  href="/login"
                  className="inline-flex items-center gap-2 bg-graphite px-6 py-3 font-display text-base font-normal tracking-display text-canvas transition-colors hover:bg-steel"
                >
                  Start free trial
                </Link>
                <a
                  href="mailto:staykaro26@gmail.com"
                  className="inline-flex items-center gap-2 border border-graphite px-6 py-3 font-display text-base font-normal tracking-display text-graphite transition-colors hover:bg-ash"
                >
                  Book a demo
                </a>
              </div>
            </div>

            {/* Contact details */}
            <div className="space-y-6">
              <ContactItem label="Email" value="staykaro26@gmail.com" />
              <ContactItem label="Response time" value="Under 4 hours on business days" />
              <ContactItem label="Current market" value="India · UAE · Global" />
              <ContactItem label="Languages supported" value="English · Hindi · Arabic · More" />
            </div>
          </div>
        </div>
      </section>

      <Footer />
    </>
  );
}

// ── Sub-components ────────────────────────────────────────────────────────────

function StatCluster() {
  return (
    <div className="relative h-full min-h-[360px]">
      {/* Main stats card */}
      <div className="absolute left-0 top-0 w-72 rounded-2xl border border-mist bg-canvas p-6 shadow-none">
        <p className="mb-4 font-body text-xs uppercase tracking-widest text-slate">
          This week
        </p>
        <div className="space-y-3">
          <StatRow label="Calls completed" value="1,247" accent />
          <StatRow label="Answer rate" value="89%" />
          <StatRow label="Avg. duration" value="3m 42s" />
          <StatRow label="No answer" value="84" />
          <StatRow label="Voicemail" value="53" />
        </div>
        <div className="mt-5 h-px bg-mist" />
        <div className="mt-4 flex items-center justify-between">
          <span className="font-body text-xs text-slate">vs last week</span>
          <span className="font-body text-xs font-medium text-ember">+14%</span>
        </div>
      </div>

      {/* Call-in-progress card */}
      <div className="absolute right-0 top-12 w-64 border border-mist bg-canvas p-5">
        <div className="mb-3 flex items-center gap-2">
          <span className="h-1.5 w-1.5 rounded-full bg-ember" />
          <span className="font-body text-xs text-ember">Live call</span>
        </div>
        <p className="mb-1 font-display text-sm font-normal tracking-display text-graphite">
          Booking confirmation
        </p>
        <p className="font-body text-xs text-slate">+971 50 123 4567 · 1m 23s</p>
        <div className="mt-4 space-y-1.5">
          <div className="rounded bg-fog px-3 py-2">
            <p className="font-body text-xs text-steel">
              &ldquo;Your reservation for 3 nights is confirmed&hellip;&rdquo;
            </p>
          </div>
        </div>
      </div>

      {/* Outcome card */}
      <div className="absolute bottom-0 left-16 w-56 border border-mist bg-ivory p-4">
        <p className="mb-2 font-body text-xs uppercase tracking-widest text-brass">
          Last call
        </p>
        <p className="font-display text-sm font-normal tracking-display text-graphite">
          Completed
        </p>
        <p className="mt-1 font-body text-xs text-slate">
          Booking confirmed · summary sent
        </p>
      </div>
    </div>
  );
}

function StatRow({
  label,
  value,
  accent = false,
}: {
  label: string;
  value: string;
  accent?: boolean;
}) {
  return (
    <div className="flex items-center justify-between">
      <span className="font-body text-sm text-steel">{label}</span>
      <span
        className={`font-display text-sm font-normal tracking-display ${accent ? "text-ember" : "text-graphite"}`}
      >
        {value}
      </span>
    </div>
  );
}

function CallSample() {
  const turns = [
    { speaker: "AI", text: "Good afternoon, this is Maya from Talla Hotel. Am I speaking with Nihal?" },
    { speaker: "Guest", text: "Yes, speaking." },
    { speaker: "AI", text: "Wonderful. I'm calling to confirm your check-in on the 3rd of September for 4 nights. Is everything still as planned?" },
    { speaker: "Guest", text: "Yes, that's correct." },
    { speaker: "AI", text: "Perfect. We'll have your room ready from 2 PM. Is there anything specific you'd like us to arrange before your arrival?" },
  ];

  return (
    <div className="space-y-4">
      {turns.map((t, i) => (
        <div key={i} className={`flex gap-3 ${t.speaker === "Guest" ? "flex-row-reverse" : ""}`}>
          <div
            className={`flex h-6 w-6 flex-none items-center justify-center text-xs ${
              t.speaker === "AI"
                ? "bg-ember text-white"
                : "bg-white/10 text-white/60"
            }`}
          >
            {t.speaker === "AI" ? "AI" : "G"}
          </div>
          <div
            className={`max-w-[200px] px-3 py-2 font-body text-xs leading-relaxed ${
              t.speaker === "AI"
                ? "bg-white/8 text-white/80"
                : "bg-white/15 text-white"
            }`}
          >
            {t.text}
          </div>
        </div>
      ))}
      <div className="mt-2 flex items-center gap-2">
        <div className="h-1 flex-1 rounded bg-white/10">
          <div className="h-1 w-3/5 rounded bg-ember" />
        </div>
        <span className="font-body text-xs text-white/40">2m 14s</span>
      </div>
    </div>
  );
}

function ContactItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="border-b border-mist pb-6">
      <p className="mb-1 font-body text-xs uppercase tracking-widest text-slate">{label}</p>
      <p className="font-display text-base font-normal tracking-display text-graphite">{value}</p>
    </div>
  );
}
