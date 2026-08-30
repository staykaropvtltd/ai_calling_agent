"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import Link from "next/link";
import { useAuth } from "../../../../lib/auth/useAuth";
import { useClientLocale } from "../../../../lib/hooks/useClientLocale";
import { useCreateCall } from "../../../../lib/hooks/useCalls";
import { Card } from "../../../../components/Card";
import { ErrorBanner } from "../../../../components/ErrorBanner";
import { FormField, inputClass } from "../../../../components/FormField";
import { Button } from "../../../../components/Button";
import { PageHeader } from "../../../../components/PageHeader";

const EMPTY_FORM = {
  customerName: "",
  phoneNumber: "",
  hotelName: "",
  checkInDate: "",
  checkOutDate: "",
};

export default function NewCallPage() {
  const { user } = useAuth();
  const { phoneCountryCode } = useClientLocale();
  const createCall = useCreateCall();
  const [form, setForm] = useState(EMPTY_FORM);
  const [justSubmittedFor, setJustSubmittedFor] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setJustSubmittedFor(null);
    await createCall.mutateAsync({
      customer_name: form.customerName,
      phone_number: form.phoneNumber.trim(),
      hotel_name: form.hotelName,
      check_in_date: form.checkInDate,
      check_out_date: form.checkOutDate,
    });
    setJustSubmittedFor(form.customerName);
    setForm(EMPTY_FORM);
  }

  return (
    <div>
      <PageHeader
        eyebrow="Calls"
        title="New Call"
        description="Place an outbound AI call to a guest."
        actions={
          <Link href="/calls">
            <Button variant="ghost" size="sm">← Back to calls</Button>
          </Link>
        }
      />

      <div className="max-w-lg">
        <Card>
          {createCall.isError ? (
            <div className="mb-5">
              <ErrorBanner error={createCall.error} />
            </div>
          ) : null}

          {justSubmittedFor ? (
            <div
              role="status"
              className="mb-5 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700"
            >
              Call to <strong>{justSubmittedFor}</strong> has been queued.
              {user?.role === "tenant_admin" ? (
                <>
                  {" "}
                  <Link href="/calls" className="font-medium underline">
                    View calls
                  </Link>
                  .
                </>
              ) : null}
            </div>
          ) : null}

          <form onSubmit={handleSubmit} className="flex flex-col gap-5">
            <FormField label="Customer name" htmlFor="customer_name">
              <input
                id="customer_name"
                required
                value={form.customerName}
                onChange={(e) => setForm((f) => ({ ...f, customerName: e.target.value }))}
                className={inputClass}
                placeholder="Guest name"
              />
            </FormField>

            <FormField
              label="Phone number"
              htmlFor="phone_number"
              hint={`E.164 format${phoneCountryCode ? ` (e.g. ${phoneCountryCode}XXXXXXXXXX)` : " (e.g. +919876543210)"}`}
            >
              <input
                id="phone_number"
                type="tel"
                required
                placeholder={phoneCountryCode ? `${phoneCountryCode}XXXXXXXXXX` : "+919876543210"}
                value={form.phoneNumber}
                onChange={(e) => setForm((f) => ({ ...f, phoneNumber: e.target.value }))}
                className={inputClass}
              />
            </FormField>

            <FormField label="Hotel name" htmlFor="hotel_name">
              <input
                id="hotel_name"
                required
                value={form.hotelName}
                onChange={(e) => setForm((f) => ({ ...f, hotelName: e.target.value }))}
                className={inputClass}
                placeholder="Hotel name"
              />
            </FormField>

            <div className="grid grid-cols-2 gap-4">
              <FormField label="Check-in date" htmlFor="check_in_date">
                <input
                  id="check_in_date"
                  type="date"
                  required
                  value={form.checkInDate}
                  onChange={(e) => setForm((f) => ({ ...f, checkInDate: e.target.value }))}
                  className={inputClass}
                />
              </FormField>
              <FormField label="Check-out date" htmlFor="check_out_date">
                <input
                  id="check_out_date"
                  type="date"
                  required
                  value={form.checkOutDate}
                  onChange={(e) => setForm((f) => ({ ...f, checkOutDate: e.target.value }))}
                  className={inputClass}
                />
              </FormField>
            </div>

            <div className="pt-2">
              <Button
                type="submit"
                variant="accent"
                size="lg"
                disabled={createCall.isPending}
              >
                {createCall.isPending ? "Placing call…" : "Place call"}
              </Button>
            </div>
          </form>
        </Card>
      </div>
    </div>
  );
}
