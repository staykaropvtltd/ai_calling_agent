import axios from "axios";

export function ErrorBanner({ error }: { error: unknown }) {
  const message = extractMessage(error);
  return (
    <div role="alert" className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
      {message}
    </div>
  );
}

function extractMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (error.response?.status === 401) return "Session expired. Please log in again.";
    if (error.message) return error.message;
  }
  if (error instanceof Error) return error.message;
  return "Something went wrong.";
}
