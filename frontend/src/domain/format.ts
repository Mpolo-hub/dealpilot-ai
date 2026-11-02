// English number formats (spec 007 section 8): `152,840`, `$12.5M`.
const counts = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

export function formatCount(value: number): string {
  return counts.format(value);
}
