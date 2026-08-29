"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import Link from "next/link";
import { useAuth } from "../../../../lib/auth/useAuth";
import { useCreateCall } from "../../../../lib/hooks/useCalls";
import { Card } from "../../../../components/Card";
import { ErrorBanner } from "../../../../components/ErrorBanner";
import { buttonClass, FormField, inputClass } from "../../../../components/FormField";

const EMPTY_FORM = {
  customerName: "",
  phoneNumber: "",
  hotelName: "",
  checkInDate: "",
  checkOutDate: "",
};

export default function NewCallPage() {
  const { user } = useAuth();
  const createCall = useCreateCall();
  const [form, setForm] = useState(EMPTY_FORM);
  const [justSubmittedFor, setJustSubmittedFor] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setJustSubmittedFor(null);
    await createCall.mutateAsync({
      customer_name: form.customerName,
      // /call's CallerRequest strips whitespace/dashes/parens before
      // validating E.164 (services/api/src/main.py) — but the raw value is
      // what's stored, so trim here to avoid a stray leading/trailing space.
      phone_number: form.phoneNumber.trim(),
      hotel_name: form.hotelName,
      check_in_date: form.checkInDate,
      check_out_date: form.checkOutDate,
    });
    setJustSubmittedFor(form.customerName);
    setForm(EMPTY_FORM);
  }

  return (
    <div className="max-w-lg">
      <h1 className="mb-6 text-xl font-semibold text-slate-900">New call</h1>
      <Card className="p-6">
        {createCall.isError ? (
          <div className="mb-4">
            <ErrorBanner error={createCall.error} />
          </div>
        ) : null}
        {justSubmittedFor ? (
          <div
            role="status"
            className="mb-4 rounded-md border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-700"
          >
            Call to {justSubmittedFor} has been queued.
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

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <FormField label="Customer name" htmlFor="customer_name">
            <input
              id="customer_name"
              required
              value={form.customerName}
              onChange={(e) => setForm((f) => ({ ...f, customerName: e.target.value }))}
              className={inputClass}
            />
          </FormField>
          <FormField label="Phone number (E.164, e.g. +919876543210)" htmlFor="phone_number">
            <input
              id="phone_number"
              type="tel"
              required
              placeholder="+919876543210"
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
            />
          </FormField>
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

          <div className="mt-2">
            <button type="submit" disabled={createCall.isPending} className={buttonClass}>
              {createCall.isPending ? "Placing call…" : "Place call"}
            </button>
          </div>
        </form>
      </Card>
    </div>
  );
}
