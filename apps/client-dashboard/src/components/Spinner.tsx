export function Spinner({ size = "md" }: { size?: "sm" | "md" | "lg" }) {
  const dim =
    size === "sm" ? "h-4 w-4 border" : size === "lg" ? "h-8 w-8 border-2" : "h-6 w-6 border-2";
  return (
    <div
      role="status"
      aria-label="Loading"
      className={`animate-spin rounded-full border-mist border-t-graphite ${dim}`}
    />
  );
}
