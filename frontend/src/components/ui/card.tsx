import * as React from "react";
import { cn } from "@/lib/utils";

export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("rounded-card border border-border bg-surface shadow-card", className)} {...props} />;
}

export function CardHeader({
  title,
  description,
  action,
  className,
  titleAs: TitleTag = "h2",
}: {
  title: React.ReactNode;
  description?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
  titleAs?: "h2" | "h3";
}) {
  return (
    <div className={cn("flex min-h-10 items-center justify-between gap-2 border-b border-border px-4 py-2", className)}>
      <div className="min-w-0">
        <TitleTag className="label-caps truncate">{title}</TitleTag>
        {description && <p className="mt-0.5 text-caption text-fg-muted">{description}</p>}
      </div>
      {action && <div className="flex shrink-0 items-center gap-1">{action}</div>}
    </div>
  );
}

export function CardBody({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("p-4", className)} {...props} />;
}

export function CardFooter({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("border-t border-border px-4 py-2 text-meta", className)} {...props} />;
}
