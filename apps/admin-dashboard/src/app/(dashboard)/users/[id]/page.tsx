"use client";

import { useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { useParams, useRouter } from "next/navigation";
import { useAuth } from "../../../../lib/auth/useAuth";
import { useDeleteUser, useUpdateUser, useUserQuery } from "../../../../lib/hooks/useUsers";
import { Card } from "../../../../components/Card";
import { ErrorBanner } from "../../../../components/ErrorBanner";
import { Spinner } from "../../../../components/Spinner";
import { StatusBadge } from "../../../../components/StatusBadge";
import { buttonClass, FormField, inputClass, secondaryButtonClass } from "../../../../components/FormField";
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
      <div className="flex justify-center py-10">
        <Spinner />
      </div>
    );
  }
  if (isError || !targetUser) {
    return <ErrorBanner error={error} />;
  }

  const canEdit = viewer?.role === "super_admin";

  async function handleSuspend() {
    await deleteUser.mutateAsync(userId);
    router.push("/users");
  }

  return (
    <div className="max-w-lg">
      <h1 className="mb-6 text-xl font-semibold text-slate-900">{targetUser.email}</h1>

      <Card className="p-6">
        {updateUser.isError ? (
          <div className="mb-4">
            <ErrorBanner error={updateUser.error} />
          </div>
        ) : null}

        {canEdit ? (
          // Keyed by user_id so local form state initializes fresh from the
          // loaded user with no effect needed.
          <UserEditForm
            key={targetUser.user_id}
            targetUser={targetUser}
            onSave={(payload) => updateUser.mutateAsync(payload)}
            onSuspend={handleSuspend}
            isSaving={updateUser.isPending}
          />
        ) : (
          <dl className="flex flex-col gap-3 text-sm">
            <Row label="Full name" value={targetUser.full_name} />
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
    <form onSubmit={handleSubmit} className="flex flex-col gap-4">
      <FormField label="Full name" htmlFor="full_name">
        <input
          id="full_name"
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
          className={inputClass}
        />
      </FormField>
      <FormField label="Role" htmlFor="role">
        <select
          id="role"
          value={role}
          onChange={(e) => setRole(e.target.value as EditableRole)}
          className={inputClass}
        >
          <option value="tenant_admin">Tenant admin</option>
          <option value="agent">Agent</option>
        </select>
      </FormField>
      <FormField label="Status" htmlFor="status">
        <select
          id="status"
          value={status}
          onChange={(e) => setStatus(e.target.value as UserStatus)}
          className={inputClass}
        >
          <option value="active">Active</option>
          <option value="suspended">Suspended</option>
        </select>
      </FormField>
      <div className="mt-2 flex gap-3">
        <button type="submit" disabled={isSaving} className={buttonClass}>
          {isSaving ? "Saving…" : "Save changes"}
        </button>
        <button type="button" onClick={onSuspend} className={secondaryButtonClass}>
          Suspend user
        </button>
      </div>
    </form>
  );
}

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="flex justify-between border-b border-slate-100 pb-2">
      <dt className="text-slate-500">{label}</dt>
      <dd className="text-slate-900">{value}</dd>
    </div>
  );
}
