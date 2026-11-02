// Size of an element, so SVG charts are drawn to their container (responsive, D12).
import { useEffect, useRef, useState } from "react";

export function useSize<T extends HTMLElement>(fallback = { width: 640, height: 260 }) {
  const ref = useRef<T | null>(null);
  const [size, setSize] = useState(fallback);
  useEffect(() => {
    const element = ref.current;
    if (element === null || typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver((entries) => {
      const box = entries[0]?.contentRect;
      if (box && box.width > 0) {
        setSize({ width: Math.round(box.width), height: Math.round(box.height) });
      }
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return [ref, size] as const;
}

export function useWidth<T extends HTMLElement>(fallback = 640) {
  const [ref, size] = useSize<T>({ width: fallback, height: 0 });
  return [ref, size.width] as const;
}
