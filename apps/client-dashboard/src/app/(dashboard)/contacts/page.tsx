"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { RoleGuard } from "../../../lib/auth/RoleGuard";
import { useCustomersQuery, useCreateCustomer } from "../../../lib/hooks/useCustomers";
import { useClientLocale } from "../../../lib/hooks/useClientLocale";
import { Card } from "../../../components/Card";
import { Table, type Column } from "../../../components/Table";
import { Pagination } from "../../../components/Pagination";
import { ErrorBanner } from "../../../components/ErrorBanner";
import { Spinner } from "../../../components/Spinner";
import { PageHeader } from "../../../components/PageHeader";
import { Button } from "../../../components/Button";
import { FormField, inputClass } from "../../../components/FormField";
import type { Customer } from "../../../lib/types/customer";

export default function ContactsPage() {
  return (
    <RoleGuard allowedRoles={["tenant_admin", "agent"]}>
      <ContactsList />
    </RoleGuard>
  );
}

function ContactsList() {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const { formatDateTime } = useClientLocale();

  function handleSearchChange(value: string) {
    setSearch(value);
    setPage(1);
    setDebouncedSearch(value);
  }

  const { data, isLoading, isError, error } = useCustomersQuery({
    page,
    per_page: 20,
    search: debouncedSearch || undefined,
  });

  const columns: Column<Customer>[] = [
    {
      key: "name",
      header: "Name",
      render: (c) => (
        <span className="font-medium text-graphite">{c.name ?? "—"}</span>
      ),
    },
    { key: "phone", header: "Phone", render: (c) => c.phone },
    { key: "email", header: "Email", render: (c) => c.email ?? "—" },
    { key: "country_code", header: "Country", render: (c) => c.country_code ?? "—" },
    {
      key: "created_at",
      header: "Added",
      render: (c) => (
        <span className="text-slate-neutral">{formatDateTime(c.created_at)}</span>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        eyebrow="Contacts"
        title="Contacts"
        description="Your hotel's guest contact database. All contacts are isolated to your account."
        actions={
          <Button variant="accent" onClick={() => setShowAdd((v) => !v)}>
            {showAdd ? "Cancel" : "+ Add contact"}
          </Button>
        }
      />

      {showAdd && (
        <div className="mb-6">
          <AddContactForm onSuccess={() => setShowAdd(false)} />
        </div>
      )}

      <div className="mb-4">
        <input
          type="search"
          placeholder="Search by name, phone, or email…"
          value={search}
          onChange={(e) => handleSearchChange(e.target.value)}
          className="w-full max-w-xs rounded-xl border border-mist bg-canvas px-4 py-2 text-sm placeholder:text-slate-neutral focus:border-steel focus:outline-none"
          aria-label="Search contacts"
        />
      </div>

      <Card padding={false}>
        {isLoading ? (
          <div className="flex justify-center py-12">
            <Spinner />
          </div>
        ) : isError ? (
          <div className="p-6">
            <ErrorBanner error={error} />
          </div>
        ) : (
          <>
            <Table
              columns={columns}
              rows={data?.data ?? []}
              rowKey={(c) => c.id}
              emptyMessage={
                debouncedSearch ? "No contacts match your search." : "No contacts yet."
              }
            />
            <Pagination
              page={page}
              totalPages={data?.total_pages ?? 0}
              onPageChange={setPage}
            />
          </>
        )}
      </Card>
    </div>
  );
}

function AddContactForm({ onSuccess }: { onSuccess: () => void }) {
  const createCustomer = useCreateCustomer();
  const [form, setForm] = useState({ name: "", phone: "", email: "" });

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    await createCustomer.mutateAsync({
      name: form.name || undefined,
      phone: form.phone,
      email: form.email || undefined,
    });
    setForm({ name: "", phone: "", email: "" });
    onSuccess();
  }

  return (
    <Card>
      <div className="mb-4 text-[11px] font-medium uppercase tracking-widest text-slate-neutral">
        Add contact
      </div>
      {createCustomer.isError && (
        <div className="mb-4">
          <ErrorBanner error={createCustomer.error} />
        </div>
      )}
      <form onSubmit={handleSubmit} className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <FormField label="Name" htmlFor="contact_name">
          <input
            id="contact_name"
            value={form.name}
            onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            className={inputClass}
            placeholder="Guest name"
          />
        </FormField>
        <FormField label="Phone (E.164)" htmlFor="contact_phone">
          <input
            id="contact_phone"
            type="tel"
            required
            value={form.phone}
            onChange={(e) => setForm((f) => ({ ...f, phone: e.target.value }))}
            className={inputClass}
            placeholder="+919876543210"
          />
        </FormField>
        <FormField label="Email" htmlFor="contact_email">
          <input
            id="contact_email"
            type="email"
            value={form.email}
            onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
            className={inputClass}
            placeholder="guest@example.com"
          />
        </FormField>
        <div className="sm:col-span-3 flex justify-end">
          <Button type="submit" variant="accent" disabled={createCustomer.isPending}>
            {createCustomer.isPending ? "Saving…" : "Save contact"}
          </Button>
        </div>
      </form>
    </Card>
  );
}
