"use client";

import type { ReactNode } from "react";

/* ─────────────────────────────────────────────────────────
 * FILTER TABLE
 * Status chips directly filter the task table.
 * ───────────────────────────────────────────────────────── */

// Ported from beautifului.dev "filter-table" (MIT). Kept: the aria-pressed chip row with its
// shadow-btn active state and count badge, the horizontal chip scroller, the column header row, and
// the collapsing-row grammar (grid-template-rows 1fr/0fr + opacity on every row).
// Replaced: the FILTERS/ROWS/PILLS fixtures and their hardcoded dot hexes -> `filters` / `rows` /
// `columns` props with token-based dot colours; the four fixed columns -> a generic `columns` array
// rendered through `renderCell`. Rows carry a `filter` key; `active === "all"` shows everything.

export interface FilterChip {
  key: string;
  label: string;
  dot?: string;
  count: number;
}

export interface FilterChipsProps {
  filters: FilterChip[];
  active: string;
  onChange: (key: string) => void;
}

export interface FilterColumn {
  key: string;
  label: string;
  width: string;
}

export interface FilterTableRow {
  key: string;
  filter: string;
  cells: Record<string, string>;
}

export interface FilterTableProps {
  filters: FilterChip[];
  active: string;
  onChange: (key: string) => void;
  columns: FilterColumn[];
  rows: FilterTableRow[];
  renderCell?: (row: FilterTableRow, column: FilterColumn) => ReactNode;
}

export function FilterChips({ filters, active, onChange }: FilterChipsProps) {
  return (
    <div
      className="-mx-1 mb-1 flex items-center gap-1 overflow-x-auto px-1 py-1"
      style={{ scrollbarWidth: "none" }}
    >
      {filters.map((f) => {
        const on = active === f.key;
        return (
          <button
            key={f.key}
            type="button"
            aria-pressed={on}
            onClick={() => onChange(f.key)}
            className={`flex h-6.5 shrink-0 items-center gap-1.5 rounded-full px-2.5 text-[12px]
                font-medium transition-[background-color,box-shadow,color] duration-200
                ${on ? "bg-surface text-ink shadow-btn" : "text-ink-2 hover:bg-hover"}`}
          >
            {f.dot && <span className="size-1.5 rounded-full" style={{ background: f.dot }} />}
            {f.label}
            <span
              className={`rounded-[4px] px-1 text-[10.5px] tabular-nums
                  ${on ? "bg-field text-ink-2" : "text-ink-3"}`}
            >
              {f.count}
            </span>
          </button>
        );
      })}
    </div>
  );
}

export function FilterTable({
  filters,
  active,
  onChange,
  columns,
  rows,
  renderCell,
}: FilterTableProps) {
  const template = columns.map((column) => column.width).join(" ");

  return (
    <div className="w-full max-w-105">
      <FilterChips filters={filters} active={active} onChange={onChange} />

      {/* table */}
      <div
        aria-label="Jadval"
        className="overflow-x-auto rounded-card bg-surface shadow-card"
        role="region"
        tabIndex={0}
        style={{ scrollbarWidth: "none" }}
      >
        <div className="min-w-[420px]">
          <div
            className="grid border-b border-line px-3 py-2 text-[11.5px] font-medium text-ink-3"
            style={{ gridTemplateColumns: template }}
          >
            {columns.map((column) => (
              <span key={column.key}>{column.label}</span>
            ))}
          </div>
          {rows.map((row) => {
            const shown = active === "all" || row.filter === active;
            return (
              <div
                key={row.key}
                className="grid transition-[grid-template-rows,opacity] duration-300"
                style={{
                  gridTemplateRows: shown ? "1fr" : "0fr",
                  opacity: shown ? 1 : 0,
                  transitionTimingFunction: "cubic-bezier(0.23, 1, 0.32, 1)",
                }}
              >
                <div className="overflow-hidden">
                  <div
                    className="grid items-center border-b
                      border-line px-3 py-2 text-[12px] transition-colors duration-100
                      last:border-0 hover:bg-hover"
                    style={{ gridTemplateColumns: template }}
                  >
                    {columns.map((column) => (
                      <span key={column.key} className="min-w-0 truncate text-ink-2">
                        {renderCell ? renderCell(row, column) : row.cells[column.key]}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

export default FilterTable;
