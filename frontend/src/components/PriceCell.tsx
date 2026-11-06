"use client";

import { useEffect, useRef, useState } from "react";
import { formatPrice } from "@/lib/format";

export const FLASH_MS = 500;

type Flash = "up" | "down" | null;

/** A price that flashes green on an uptick and red on a downtick, then fades back. */
export function PriceCell({ value }: { value: number | null }) {
  const [flash, setFlash] = useState<Flash>(null);
  const previous = useRef<number | null>(value);

  useEffect(() => {
    const before = previous.current;
    previous.current = value;
    if (value == null || before == null || value === before) return;
    setFlash(value > before ? "up" : "down");
    const timer = setTimeout(() => setFlash(null), FLASH_MS);
    return () => clearTimeout(timer);
  }, [value]);

  const flashClass = flash === "up" ? "flash-up" : flash === "down" ? "flash-down" : "";
  return (
    <span data-testid="price" data-flash={flash ?? "none"} className={`tabular-nums rounded px-1 ${flashClass}`}>
      {formatPrice(value)}
    </span>
  );
}
