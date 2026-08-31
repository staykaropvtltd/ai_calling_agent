"use client";

import { useState } from "react";
import type { FormEvent, ReactNode } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useAuth } from "../../../../lib/auth/useAuth";
import { useDeleteUser, useUpdateUser, useUserQuery } from "../../../../lib/hooks/useUsers";
import { Card } from "../../../../components/Card";
import { ErrorBanner } from "../../../../components/ErrorBanner";
import { Spinner } from "../../../../components/Spinner";
import { StatusBadge } from "../../../../components/StatusBadge";
import { FormField, inputClass } from "../../../../components/FormField";
import { PageHeader } from "../../../../components/PageHeader";
import { Button } from "../../../../components/Button";
import type { TenantUser, UserStatus } from "../../../../lib/types/user";

type EditableRole = "tenant_admin" | "agent";

export default function UserDetailPage() {
  const params = useParams<{ id: string }>();
  const userId = params.id;
  const { user: viewer } = useAuth();

  const { data: targetUser, isLoading, isError, error } = useUserQuery(userId);
  const updateUser = useUpdateUser(userId);
  const deleteUser = useDeleteUser();
  const router = useRouter();

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <Spinner />
      </div>
    );
  }
  if (isError || !targetUser) {
    return (
      <div className="max-w-lg">
        <ErrorBanner error={error} />
      </div>
    );
  }

  const canEdit = viewer?.role === "super_admin";

  async function handleSuspend() {
    await deleteUser.mutateAsync(userId);
    router.push("/users");
  }

  return (
    <div className="max-w-lg">
      <PageHeader
        eyebrow="Users"
        title={targetUser.full_name || targetUser.email}
        actions={
          <Link href="/users">
            <Button variant="ghost" size="sm">← All users</Button>
          </Link>
        }
      />

      <Card>
        {updateUser.isError ? (
          <div className="mb-5">
            <ErrorBanner error={updateUser.error} />
          </div>
        ) : null}

        {canEdit ? (
          // Keyed by user_id so form state re-initialises from the loaded user
          <UserEditForm
            key={targetUser.user_id}
            targetUser={targetUser}
            onSave={(payload) => updateUser.mutateAsync(payload)}
            onSuspend={handleSuspend}
            isSaving={updateUser.isPending}
          />
        ) : (
          <dl className="divide-y divide-mist">
            <Row label="Full name" value={targetUser.full_name || "—"} />
            <Row label="Role" value={<StatusBadge value={targetUser.role} />} />
            <Row label="Status" value={<StatusBadge value={targetUser.status} />} />
          </dl>
        )}
      </Card>
    </div>
  );
}

interface UserEditFormProps {
  targetUser: TenantUser;
  onSave: (payload: { full_name: string; role: EditableRole; status: UserStatus }) => Promise<unknown>;
  onSuspend: () => void;
  isSaving: boolean;
}

function UserEditForm({ targetUser, onSave, onSuspend, isSaving }: UserEditFormProps) {
  const [fullName, setFullName] = useState(targetUser.full_name);
  const [role, setRole] = useState<EditableRole>(
    targetUser.role === "tenant_admin" || targetUser.role === "agent" ? targetUser.role : "agent",
  );
  const [status, setStatus] = useState<UserStatus>(targetUser.status);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    await onSave({ full_name: fullName, role, status });
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-5">
      <FormField label="Full name" htmlFor="full_name">
        <input id="full_name" value={fullName} onChange={(e) => setFullName(e.target.value)} className={inputClass} />
      </FormField>
      <FormField label="Role" htmlFor="role">
        <select id="role" value={role} onChange={(e) => setRole(e.target.value as EditableRole)} className={inputClass}>
          <option value="tenant_admin">Tenant admin</option>
          <option value="agent">Agent</option>
        </select>
      </FormField>
      <FormField label="Status" htmlFor="status">
        <select id="status" value={status} onChange={(e) => setStatus(e.target.value as UserStatus)} className={inputClass}>
          <option value="active">Active</option>
          <option value="suspended">Suspended</option>
        </select>
      </FormField>
      <div className="flex gap-3 pt-2">
        <button type="submit" disabled={isSaving} className="bg-graphite px-5 py-2.5 font-display text-sm font-medium text-white transition-colors hover:bg-steel disabled:opacity-50">
          {isSaving ? "Saving…" : "Save changes"}
        </button>
        <Button type="button" variant="danger" onClick={onSuspend}>
          Suspend user
        </Button>
      </div>
    </form>
  );
}

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex items-center justify-between py-3">
      <dt className="text-xs font-medium uppercase tracking-widest text-slate-neutral">{label}</dt>
      <dd className="text-sm text-graphite">{value}</dd>
    </div>
  );
}
