import * as React from "react";
import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

export function PageHeader({
  title,
  description,
  actions,
  breadcrumbs,
  className,
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  breadcrumbs?: { label: string; href?: string }[];
  className?: string;
}) {
  return (
    <div className={cn("mb-4 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between", className)}>
      <div className="min-w-0">
        {breadcrumbs && breadcrumbs.length > 0 && (
          <nav aria-label="Breadcrumb" className="mb-1">
            <ol className="flex flex-wrap items-center gap-1 text-caption text-fg-muted">
              {breadcrumbs.map((b, i) => (
                <li key={`${b.label}-${i}`} className="flex items-center gap-1">
                  {b.href ? (
                    <Link href={b.href} className="hover:text-fg hover:underline">
                      {b.label}
                    </Link>
                  ) : (
                    <span aria-current="page">{b.label}</span>
                  )}
                  {i < breadcrumbs.length - 1 && <ChevronRight className="size-3" aria-hidden />}
                </li>
              ))}
            </ol>
          </nav>
        )}
        <h1 className="truncate text-title font-semibold">{title}</h1>
        {description && <p className="mt-0.5 text-meta text-fg-muted">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Section({
  title,
  description,
  actions,
  children,
  className,
}: {
  title: string;
  description?: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("flex flex-col gap-3", className)} aria-label={title}>
      <div className="flex items-end justify-between gap-2">
        <div>
          <h2 className="text-section font-semibold">{title}</h2>
          {description && <p className="text-meta text-fg-muted">{description}</p>}
        </div>
        {actions}
      </div>
      {children}
    </section>
  );
}

/** Secondary navigation for a resource (e.g. team overview / members / questions / schedule). */
export function SubNav({ items }: { items: { href: string; label: string; active: boolean }[] }) {
  return (
    <nav aria-label="Section" className="mb-4 flex gap-4 overflow-x-auto border-b border-border">
      {items.map((i) => (
        <Link
          key={i.href}
          href={i.href}
          aria-current={i.active ? "page" : undefined}
          className={cn(
            "-mb-px inline-flex h-9 shrink-0 items-center border-b-2 border-transparent text-body font-medium text-fg-muted hover:text-fg",
            i.active && "border-teal-600 text-teal-700",
          )}
        >
          {i.label}
        </Link>
      ))}
    </nav>
  );
}
