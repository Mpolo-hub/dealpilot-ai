// Small line icons drawn in SVG (no icon dependency). Decorative: hidden from assistive
// technology; every icon sits next to a text label.
import type { ReactElement } from "react";

const paths = {
  logo: <><rect x="3" y="13" width="3.5" height="8" rx="1" /><rect x="9" y="8" width="3.5"
    height="13" rx="1" /><rect x="15" y="3" width="3.5" height="18" rx="1" /></>,
  dashboard: <><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7"
    height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14"
    y="14" width="7" height="7" rx="1.5" /></>,
  data: <><ellipse cx="12" cy="5.5" rx="8" ry="3" /><path d="M4 5.5v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6" />
    <path d="M4 11.5v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6" /></>,
  analysis: <><path d="M3 20h18" /><path d="M5 16l5-5 4 3 6-7" /></>,
  products: <><path d="M12 2.5l8.5 4.5v10L12 21.5 3.5 17V7z" /><path d="M3.5 7L12 11.5 20.5 7" />
    <path d="M12 11.5v10" /></>,
  money: <><rect x="2.5" y="6" width="19" height="12" rx="2" /><circle cx="12" cy="12" r="3" /></>,
  orders: <><path d="M6 3h12v18l-3-2-3 2-3-2-3 2z" /><path d="M9 8h6M9 12h6" /></>,
  box: <><path d="M3 7l9-4 9 4-9 4z" /><path d="M3 7v10l9 4 9-4V7" /></>,
  users: <><circle cx="9" cy="8" r="3.5" /><path d="M2.5 20c0-3.6 2.9-6 6.5-6s6.5 2.4 6.5 6" />
    <path d="M16 4.5a3.5 3.5 0 010 7M18 14.2c2 .8 3.5 2.8 3.5 5.8" /></>,
  calendar: <><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M3 10h18M8 3v4M16 3v4" /></>,
  trophy: <><path d="M7 4h10v4a5 5 0 01-10 0z" /><path d="M7 6H4a3 3 0 003 4M17 6h3a3 3 0 01-3 4" />
    <path d="M12 13v4M8 21h8" /></>,
  pin: <><path d="M12 21s7-6.2 7-11.5A7 7 0 005 9.5C5 14.8 12 21 12 21z" /><circle cx="12" cy="9.5" r="2.5" /></>,
  trend: <><path d="M3 17l6-6 4 4 8-8" /><path d="M15 7h6v6" /></>,
  table: <><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M3 9h18M9 9v11" /></>,
  file: <><path d="M6 2.5h8l4 4V21.5H6z" /><path d="M14 2.5v4h4" /></>,
  pie: <><path d="M12 3a9 9 0 109 9h-9z" /><path d="M15 2.6A9 9 0 0121.4 9H15z" /></>,
  bars: <><path d="M5 20V11M10 20V6M15 20v-7M20 20V9" /></>,
  info: <><circle cx="12" cy="12" r="9" /><path d="M12 11v6M12 7.5v.5" /></>,
  menu: <path d="M4 6h16M4 12h16M4 18h16" />,
  close: <path d="M6 6l12 12M18 6L6 18" />,
  search: <><circle cx="11" cy="11" r="6.5" /><path d="M20 20l-4.2-4.2" /></>,
} satisfies Record<string, ReactElement>;

export type IconName = keyof typeof paths;

export function Icon({ name, size = 18 }: { name: IconName; size?: number }) {
  const filled = name === "logo";
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" focusable="false"
      fill={filled ? "currentColor" : "none"} stroke={filled ? "none" : "currentColor"}
      strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      {paths[name]}
    </svg>
  );
}
