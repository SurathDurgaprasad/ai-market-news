import type { ReactNode } from "react";
import { categoryColor } from "@/lib/categories";

/** Category label with its hue-family marker. Renders nothing without a category. */
export function CategoryTag({ category, className = "" }: { category?: string | null; className?: string }) {
  if (!category) return null;
  return (
    <span
      className={`inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.12em] ${className}`}
      style={{ color: categoryColor(category) }}
    >
      <span className="h-1.5 w-1.5 shrink-0 rounded-[1px]" style={{ background: categoryColor(category) }} aria-hidden="true" />
      {category}
    </span>
  );
}

/** Kicker, title and optional definition, shared by every section. */
export function SectionHeading({
  id,
  kicker,
  title,
  note,
  aside,
}: {
  id: string;
  kicker: string;
  title: string;
  note?: ReactNode;
  aside?: ReactNode;
}) {
  return (
    <div className="mb-3 flex flex-wrap items-end justify-between gap-x-6 gap-y-1 border-b border-line pb-2.5">
      <div className="min-w-0">
        <p className="intel-kicker">{kicker}</p>
        <h2 id={id} className="mt-0.5 scroll-mt-20 text-[18px] font-semibold tracking-tight text-ink">
          {title}
        </h2>
        {note ? <p className="mt-0.5 max-w-[72ch] text-[12.5px] leading-relaxed text-muted">{note}</p> : null}
      </div>
      {aside ? <div className="shrink-0">{aside}</div> : null}
    </div>
  );
}

/** "3 publishers" as corroboration, not a raw statistic. Nothing for a single report. */
export function PublisherCount({ count }: { count?: number }) {
  if (!count || count < 2) return null;
  return (
    <span className="inline-flex items-center gap-1 text-secondary" title="Distinct publishers reporting this development">
      <span className="tabular">{count}</span> publishers
    </span>
  );
}
