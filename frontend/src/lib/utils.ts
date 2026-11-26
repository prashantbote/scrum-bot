import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

/** Teach tailwind-merge the custom type scale so `text-caption` doesn't override `text-fg-muted`. */
const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      "font-size": [{ text: ["caption", "meta", "body", "section", "title", "kpi"] }],
      h: [{ h: ["control", "row", "topbar"] }],
      w: [{ w: ["nav", "nav-collapsed"] }],
    },
  },
});

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
