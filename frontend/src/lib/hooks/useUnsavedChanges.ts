"use client";

import * as React from "react";

/** Warn before leaving the page with unsaved edits (plan §6: dirty-state guard). */
export function useUnsavedChanges(dirty: boolean) {
  React.useEffect(() => {
    if (!dirty) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);
}
