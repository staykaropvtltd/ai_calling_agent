"use client";

import { useState, useRef } from "react";
import type { ChangeEvent } from "react";
import Link from "next/link";
import { RoleGuard } from "../../../lib/auth/RoleGuard";
import { useCampaignsQuery } from "../../../lib/hooks/useCampaigns";
import { usePreviewUpload, useImportSheet } from "../../../lib/hooks/useCampaigns";
import { Card } from "../../../components/Card";
import { ErrorBanner } from "../../../components/ErrorBanner";
import { Spinner } from "../../../components/Spinner";
import { PageHeader } from "../../../components/PageHeader";
import { Button } from "../../../components/Button";
import type { UploadPreviewResponse } from "../../../lib/api/campaigns";

export default function UploadPage() {
  return (
    <RoleGuard allowedRoles={["tenant_admin"]}>
      <SheetUpload />
    </RoleGuard>
  );
}

type Step = "select" | "preview" | "map" | "import" | "done";

function SheetUpload() {
  const [step, setStep] = useState<Step>("select");
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<UploadPreviewResponse | null>(null);
  const [phoneColumn, setPhoneColumn] = useState("");
  const [nameColumn, setNameColumn] = useState("");
  const [emailColumn, setEmailColumn] = useState("");
  const [campaignId, setCampaignId] = useState("");
  const [importResult, setImportResult] = useState<{ imported: number; skipped: number } | null>(
    null,
  );
  const fileRef = useRef<HTMLInputElement>(null);

  const previewMutation = usePreviewUpload();
  const importMutation = useImportSheet();
  const campaigns = useCampaignsQuery({ per_page: 100 });

  async function handleFileChange(e: ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (!f) return;
    setFile(f);
    try {
      const result = await previewMutation.mutateAsync(f);
      setPreview(result);
      // Auto-detect phone/name/email columns
      const cols = result.columns;
      const phoneCol = cols.find((c) =>
        ["phone", "mobile", "number", "phone_number"].some((k) => c.toLowerCase().includes(k)),
      );
      const nameCol = cols.find((c) =>
        ["name", "guest_name", "customer_name"].some((k) => c.toLowerCase().includes(k)),
      );
      const emailCol = cols.find((c) => c.toLowerCase().includes("email"));
      if (phoneCol) setPhoneColumn(phoneCol);
      if (nameCol) setNameColumn(nameCol);
      if (emailCol) setEmailColumn(emailCol);
      setStep("preview");
    } catch {
      // error shown below
    }
  }

  async function handleImport() {
    if (!file || !campaignId || !phoneColumn) return;
    try {
      const result = await importMutation.mutateAsync({
        file,
        campaignId,
        phoneColumn,
        nameColumn: nameColumn || undefined,
        emailColumn: emailColumn || undefined,
      });
      setImportResult({ imported: result.imported, skipped: result.skipped });
      setStep("done");
    } catch {
      // error shown below
    }
  }

  return (
    <div>
      <PageHeader
        eyebrow="Campaigns"
        title="Sheet Upload"
        description="Upload a CSV file to import contacts into a calling campaign."
      />

      <div className="max-w-2xl space-y-5">
        {/* Step 1: File selection */}
        <Card>
          <div className="mb-3 text-[11px] font-medium uppercase tracking-widest text-slate-neutral">
            1. Select file
          </div>
          <p className="mb-4 text-sm text-steel">
            Upload a CSV file containing your contact list. Maximum 5,000 rows, 10 MB.
          </p>
          <div className="flex items-center gap-3">
            <input
              ref={fileRef}
              type="file"
              accept=".csv"
              onChange={handleFileChange}
              className="hidden"
            />
            <Button
              variant="outline"
              onClick={() => fileRef.current?.click()}
              disabled={previewMutation.isPending}
            >
              {previewMutation.isPending ? "Parsing…" : "Choose CSV file"}
            </Button>
            {file && (
              <span className="text-sm text-steel">
                {file.name} ({(file.size / 1024).toFixed(0)} KB)
              </span>
            )}
          </div>
          {previewMutation.isError && (
            <div className="mt-3">
              <ErrorBanner error={previewMutation.error} />
            </div>
          )}
        </Card>

        {/* Step 2: Preview */}
        {step !== "select" && preview && (
          <Card>
            <div className="mb-3 text-[11px] font-medium uppercase tracking-widest text-slate-neutral">
              2. File preview
            </div>
            <div className="mb-4 flex gap-6 text-sm">
              <div>
                <span className="font-medium text-graphite">{preview.total_rows}</span>{" "}
                <span className="text-slate-neutral">total rows</span>
              </div>
              <div>
                <span className="font-medium text-emerald-700">{preview.valid_rows}</span>{" "}
                <span className="text-slate-neutral">valid</span>
              </div>
              {preview.invalid_rows > 0 && (
                <div>
                  <span className="font-medium text-red-600">{preview.invalid_rows}</span>{" "}
                  <span className="text-slate-neutral">invalid (no phone)</span>
                </div>
              )}
            </div>
            <div className="overflow-x-auto rounded-lg border border-mist">
              <table className="min-w-full text-xs">
                <thead className="bg-fog">
                  <tr>
                    {preview.columns.map((col) => (
                      <th
                        key={col}
                        className="px-3 py-2 text-left font-medium uppercase tracking-wider text-slate-neutral"
                      >
                        {col}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {preview.preview.slice(0, 5).map((row) => (
                    <tr
                      key={row.row_number}
                      className={row.error ? "bg-red-50" : "odd:bg-canvas even:bg-fog/30"}
                    >
                      {preview.columns.map((col) => (
                        <td key={col} className="px-3 py-2 text-steel">
                          {row.data[col] ?? "—"}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {preview.preview.length > 5 && (
              <p className="mt-2 text-xs text-slate-neutral">
                Showing 5 of {preview.total_rows} rows.
              </p>
            )}
          </Card>
        )}

        {/* Step 3: Column mapping + campaign selection */}
        {step !== "select" && preview && (
          <Card>
            <div className="mb-3 text-[11px] font-medium uppercase tracking-widest text-slate-neutral">
              3. Map columns &amp; select campaign
            </div>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <label className="mb-1.5 block text-xs font-medium uppercase tracking-widest text-steel">
                  Phone column <span className="text-red-500">*</span>
                </label>
                <select
                  value={phoneColumn}
                  onChange={(e) => setPhoneColumn(e.target.value)}
                  className="w-full rounded-xl border border-mist bg-canvas px-4 py-2.5 text-sm text-graphite focus:border-steel focus:outline-none"
                >
                  <option value="">— select —</option>
                  {preview.columns.map((col) => (
                    <option key={col} value={col}>
                      {col}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-medium uppercase tracking-widest text-steel">
                  Name column
                </label>
                <select
                  value={nameColumn}
                  onChange={(e) => setNameColumn(e.target.value)}
                  className="w-full rounded-xl border border-mist bg-canvas px-4 py-2.5 text-sm text-graphite focus:border-steel focus:outline-none"
                >
                  <option value="">— none —</option>
                  {preview.columns.map((col) => (
                    <option key={col} value={col}>
                      {col}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-medium uppercase tracking-widest text-steel">
                  Email column
                </label>
                <select
                  value={emailColumn}
                  onChange={(e) => setEmailColumn(e.target.value)}
                  className="w-full rounded-xl border border-mist bg-canvas px-4 py-2.5 text-sm text-graphite focus:border-steel focus:outline-none"
                >
                  <option value="">— none —</option>
                  {preview.columns.map((col) => (
                    <option key={col} value={col}>
                      {col}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="mb-1.5 block text-xs font-medium uppercase tracking-widest text-steel">
                  Campaign <span className="text-red-500">*</span>
                </label>
                {campaigns.isLoading ? (
                  <Spinner />
                ) : (
                  <select
                    value={campaignId}
                    onChange={(e) => setCampaignId(e.target.value)}
                    className="w-full rounded-xl border border-mist bg-canvas px-4 py-2.5 text-sm text-graphite focus:border-steel focus:outline-none"
                  >
                    <option value="">— select campaign —</option>
                    {campaigns.data?.data
                      .filter((c) => c.status === "draft" || c.status === "scheduled")
                      .map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.name}
                        </option>
                      ))}
                  </select>
                )}
                {campaigns.data?.data.filter(
                  (c) => c.status === "draft" || c.status === "scheduled",
                ).length === 0 && (
                  <p className="mt-1 text-xs text-slate-neutral">
                    No draft campaigns.{" "}
                    <Link href="/campaigns" className="text-graphite underline">
                      Create one first.
                    </Link>
                  </p>
                )}
              </div>
            </div>

            {importMutation.isError && (
              <div className="mt-4">
                <ErrorBanner error={importMutation.error} />
              </div>
            )}

            <div className="mt-5 flex justify-end">
              <Button
                variant="accent"
                disabled={!phoneColumn || !campaignId || importMutation.isPending}
                onClick={handleImport}
              >
                {importMutation.isPending ? "Importing…" : `Import ${preview.valid_rows} contacts`}
              </Button>
            </div>
          </Card>
        )}

        {/* Done */}
        {step === "done" && importResult && (
          <Card tint="ivory">
            <div className="text-[11px] font-medium uppercase tracking-widest text-brass mb-2">
              Import complete
            </div>
            <p className="text-sm text-steel mb-4">
              <span className="font-medium text-graphite">{importResult.imported}</span> contacts
              imported
              {importResult.skipped > 0 && (
                <>, <span className="font-medium text-graphite">{importResult.skipped}</span> rows skipped (no phone number)</>
              )}
              .
            </p>
            <div className="flex gap-3">
              <Link href="/campaigns">
                <Button variant="accent" size="sm">View campaigns</Button>
              </Link>
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setStep("select");
                  setFile(null);
                  setPreview(null);
                  setImportResult(null);
                  setCampaignId("");
                  setPhoneColumn("");
                  setNameColumn("");
                  setEmailColumn("");
                  if (fileRef.current) fileRef.current.value = "";
                }}
              >
                Upload another
              </Button>
            </div>
          </Card>
        )}
      </div>
    </div>
  );
}
