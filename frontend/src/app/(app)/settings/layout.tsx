"use client";

import * as React from "react";
import { usePathname } from "next/navigation";
import { PageHeader, SubNav } from "@/components/layout/PageHeader";

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const items = [
    { href: "/settings/org", label: "Organization" },
    { href: "/settings/retention", label: "Privacy & retention" },
    { href: "/settings/users", label: "Users & roles" },
  ].map((i) => ({ ...i, active: pathname === i.href }));
  return (
    <>
      <PageHeader title="Settings" description="Organization-wide configuration. Every change is recorded in the audit log." />
      <SubNav items={items} />
      {children}
    </>
  );
}
