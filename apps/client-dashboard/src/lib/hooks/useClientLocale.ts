"use client";

import { useClientProfileQuery } from "./useSettings";
import { useAuth } from "../auth/useAuth";

export interface ClientLocale {
  /** IANA timezone, e.g. "Asia/Dubai". Defaults to "UTC" when unset. */
  timezone: string;
  /** ISO 4217 currency code, e.g. "AED". Defaults to "USD" when unset. */
  currency: string;
  /** BCP 47 locale tag for Intl APIs, e.g. "en-AE". Defaults to "en" when unset. */
  locale: string;
  /** Dial prefix for phone number hints, e.g. "+971". Defaults to "" when unset. */
  phoneCountryCode: string;
  /** ISO 3166-1 α-2 country code, e.g. "AE". Null when unset. */
  country: string | null;
  /** Format a UTC ISO string for display in the client's timezone. */
  formatDate: (iso: string | null | undefined) => string;
  formatDateTime: (iso: string | null | undefined) => string;
}

/**
 * Provides the authenticated client's locale settings so every page can
 * display timestamps, currencies, and phone hints in the right format without
 * hard-coding India-specific values.
 *
 * Falls back to UTC / USD / "en" when:
 *  - The profile hasn't loaded yet.
 *  - The tenant has not configured internationalisation settings.
 *
 * Pages that display timestamps should use formatDate / formatDateTime rather
 * than Date.toLocaleString() directly.
 */
export function useClientLocale(): ClientLocale {
  const { user } = useAuth();
  const isTenantAdmin = user?.role === "tenant_admin";
  // Agents have a tenant too — profile is accessible to both roles.
  const { data: profile } = useClientProfileQuery({ enabled: !!user });

  const timezone = profile?.timezone ?? "UTC";
  const currency = profile?.currency ?? "USD";
  const lang = profile?.default_language ?? "en";
  const country = profile?.country ?? null;
  const phoneCountryCode = profile?.phone_country_code ?? "";

  // Build a locale tag: "en-AE", "en-IN", or just "en" when no country.
  const locale = country ? `${lang}-${country}` : lang;

  function formatDate(iso: string | null | undefined): string {
    if (!iso) return "—";
    try {
      return new Intl.DateTimeFormat(locale, {
        timeZone: timezone,
        year: "numeric",
        month: "short",
        day: "numeric",
      }).format(new Date(iso));
    } catch {
      return new Date(iso).toLocaleDateString();
    }
  }

  function formatDateTime(iso: string | null | undefined): string {
    if (!iso) return "—";
    try {
      return new Intl.DateTimeFormat(locale, {
        timeZone: timezone,
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      }).format(new Date(iso));
    } catch {
      return new Date(iso).toLocaleString();
    }
  }

  return {
    timezone,
    currency,
    locale,
    phoneCountryCode,
    country,
    formatDate,
    formatDateTime,
  };
}
