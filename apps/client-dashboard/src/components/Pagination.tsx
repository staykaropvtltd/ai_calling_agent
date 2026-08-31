interface PaginationProps {
  page: number;
  totalPages: number;
  onPageChange: (page: number) => void;
}

export function Pagination({ page, totalPages, onPageChange }: PaginationProps) {
  if (totalPages <= 1) return null;

  return (
    <div className="flex items-center justify-between border-t border-mist px-6 py-3">
      <button
        type="button"
        onClick={() => onPageChange(page - 1)}
        disabled={page <= 1}
        className="font-display text-xs font-medium text-steel transition-colors hover:text-graphite disabled:opacity-30"
      >
        ← Previous
      </button>
      <span className="text-xs text-slate-neutral">
        {page} / {totalPages}
      </span>
      <button
        type="button"
        onClick={() => onPageChange(page + 1)}
        disabled={page >= totalPages}
        className="font-display text-xs font-medium text-steel transition-colors hover:text-graphite disabled:opacity-30"
      >
        Next →
      </button>
    </div>
  );
}
