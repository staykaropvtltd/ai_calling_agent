import type { ReactNode } from "react";

export interface Column<T> {
  header: string;
  render: (row: T) => ReactNode;
  key: string;
}

interface TableProps<T> {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  emptyMessage?: string;
}

export function Table<T>({ columns, rows, rowKey, onRowClick, emptyMessage }: TableProps<T>) {
  if (rows.length === 0) {
    return (
      <div className="px-6 py-12 text-center text-sm text-slate-neutral">
        {emptyMessage ?? "No results."}
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full">
        <thead>
          <tr className="border-b border-mist bg-fog">
            {columns.map((col) => (
              <th
                key={col.key}
                className="px-4 py-3 text-left text-[11px] font-medium uppercase tracking-widest text-slate-neutral"
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr
              key={rowKey(row)}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              className={[
                i % 2 === 0 ? "bg-canvas" : "bg-fog",
                "border-b border-mist transition-colors",
                onRowClick ? "cursor-pointer hover:bg-ash" : "",
              ].join(" ")}
            >
              {columns.map((col) => (
                <td key={col.key} className="whitespace-nowrap px-4 py-3 text-sm text-steel">
                  {col.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
