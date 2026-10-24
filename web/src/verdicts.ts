import type { Verdict } from "./api";

export const VERDICT_TEXT_CLASSES: Record<Verdict, string> = {
  READY: "text-green-700",
  GAP: "text-red-700",
  UNKNOWN: "text-amber-700",
};
