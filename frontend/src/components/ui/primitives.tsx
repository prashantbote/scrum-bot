"use client";

import * as React from "react";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import * as DropdownPrimitive from "@radix-ui/react-dropdown-menu";
import * as SwitchPrimitive from "@radix-ui/react-switch";
import { Info, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { initials } from "@/lib/format";

/* ---------------- Tabs ---------------- */
export const Tabs = TabsPrimitive.Root;

export function TabsList({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.List>) {
  return <TabsPrimitive.List className={cn("flex gap-4 border-b border-border", className)} {...props} />;
}

export function TabsTrigger({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      className={cn(
        "-mb-px inline-flex h-9 items-center gap-1.5 border-b-2 border-transparent text-body font-medium text-fg-muted hover:text-fg data-[state=active]:border-teal-600 data-[state=active]:text-teal-700",
        className,
      )}
      {...props}
    />
  );
}

export const TabsContent = ({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Content>) => (
  <TabsPrimitive.Content className={cn("pt-4", className)} {...props} />
);

/* ---------------- Dialog / Sheet ---------------- */
export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;

export function DialogContent({
  title,
  description,
  side,
  className,
  children,
}: {
  title: string;
  description?: string;
  /** "right" renders a drawer (sheet); default is a centered dialog. */
  side?: "right";
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-40 bg-overlay" />
      <DialogPrimitive.Content
        className={cn(
          "fixed z-50 flex flex-col border border-border bg-surface shadow-popover focus-visible:shadow-popover",
          side === "right"
            ? "inset-y-0 right-0 w-full max-w-md"
            : "left-1/2 top-1/2 max-h-[85vh] w-[calc(100%-32px)] max-w-lg -translate-x-1/2 -translate-y-1/2 rounded-card",
          className,
        )}
      >
        <div className="flex items-start justify-between gap-2 border-b border-border px-4 py-3">
          <div>
            <DialogPrimitive.Title className="text-section font-semibold">{title}</DialogPrimitive.Title>
            {description ? (
              <DialogPrimitive.Description className="text-meta text-fg-muted">{description}</DialogPrimitive.Description>
            ) : (
              <DialogPrimitive.Description className="sr-only">{title}</DialogPrimitive.Description>
            )}
          </div>
          <DialogPrimitive.Close
            className="inline-flex size-7 items-center justify-center rounded-control text-fg-muted hover:bg-surface-muted"
            aria-label="Close"
          >
            <X className="size-4" />
          </DialogPrimitive.Close>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-4">{children}</div>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}

/* ---------------- Tooltip ---------------- */
export const TooltipProvider = TooltipPrimitive.Provider;

export function Tooltip({ content, children }: { content: React.ReactNode; children: React.ReactNode }) {
  return (
    <TooltipPrimitive.Root delayDuration={200}>
      <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Content
          sideOffset={4}
          className="z-50 max-w-xs rounded-control bg-fg px-2 py-1 text-caption text-white shadow-popover"
        >
          {content}
        </TooltipPrimitive.Content>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}

/** Small "i" button explaining how a metric is calculated (plan §7). */
export function InfoTip({ text, label = "How this is calculated" }: { text: string; label?: string }) {
  return (
    <Tooltip content={text}>
      <button
        type="button"
        aria-label={`${label}: ${text}`}
        className="-my-1 inline-flex size-6 items-center justify-center rounded-control text-fg-subtle hover:text-fg-muted"
      >
        <Info className="size-3.5" />
      </button>
    </Tooltip>
  );
}

/* ---------------- Dropdown menu ---------------- */
export const DropdownMenu = DropdownPrimitive.Root;
export const DropdownMenuTrigger = DropdownPrimitive.Trigger;

export function DropdownMenuContent({ className, ...props }: React.ComponentProps<typeof DropdownPrimitive.Content>) {
  return (
    <DropdownPrimitive.Portal>
      <DropdownPrimitive.Content
        sideOffset={4}
        align="end"
        className={cn("z-50 min-w-48 rounded-card border border-border bg-surface p-1 shadow-popover", className)}
        {...props}
      />
    </DropdownPrimitive.Portal>
  );
}

export function DropdownMenuItem({ className, ...props }: React.ComponentProps<typeof DropdownPrimitive.Item>) {
  return (
    <DropdownPrimitive.Item
      className={cn(
        "flex h-8 cursor-pointer select-none items-center gap-2 rounded-control px-2 text-body text-fg outline-none data-[highlighted]:bg-surface-muted [&_svg]:size-4 [&_svg]:text-fg-muted",
        className,
      )}
      {...props}
    />
  );
}

export function DropdownMenuLabel({ className, ...props }: React.ComponentProps<typeof DropdownPrimitive.Label>) {
  return <DropdownPrimitive.Label className={cn("px-2 py-1.5", className)} {...props} />;
}

export const DropdownMenuSeparator = () => <DropdownPrimitive.Separator className="my-1 h-px bg-border" />;

/* ---------------- Switch ---------------- */
export function Switch({ className, ...props }: React.ComponentProps<typeof SwitchPrimitive.Root>) {
  return (
    <SwitchPrimitive.Root
      className={cn(
        "inline-flex h-5 w-9 shrink-0 items-center rounded-full border border-transparent bg-border-strong transition-colors data-[state=checked]:bg-teal-600 disabled:opacity-50",
        className,
      )}
      {...props}
    >
      <SwitchPrimitive.Thumb className="block size-4 translate-x-0.5 rounded-full bg-white shadow-card transition-transform data-[state=checked]:translate-x-[17px]" />
    </SwitchPrimitive.Root>
  );
}

/* ---------------- Misc ---------------- */
export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn("animate-pulse rounded-control bg-neutral-bg", className)} />;
}

export function Avatar({ name, size = 28, className }: { name: string; size?: number; className?: string }) {
  return (
    <span
      aria-hidden
      style={{ width: size, height: size, fontSize: Math.round(size * 0.4) }}
      className={cn(
        "inline-flex shrink-0 items-center justify-center rounded-full bg-blue-50 font-semibold text-blue-700",
        className,
      )}
    >
      {initials(name)}
    </span>
  );
}

/** Horizontal confidence meter with text, so it never relies on color alone. */
export function ConfidenceBar({ value, className }: { value: number; className?: string }) {
  const pctValue = Math.round(value * 100);
  const tone = value >= 0.85 ? "bg-teal-600" : value >= 0.6 ? "bg-warning" : "bg-danger";
  return (
    <div className={cn("flex items-center gap-2", className)}>
      <div
        className="h-1.5 w-20 overflow-hidden rounded-full bg-neutral-bg"
        role="meter"
        aria-valuenow={pctValue}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Match confidence"
      >
        <div className={cn("h-full rounded-full", tone)} style={{ width: `${pctValue}%` }} />
      </div>
      <span className="tabular text-caption text-fg-muted">{pctValue}%</span>
    </div>
  );
}
