// English number formats (spec 007 section 8): `152,840`, `$12.5M`. The locale tag comes
// from the text catalog.
import { text } from "../text/en";

const counts = new Intl.NumberFormat(text.formats.locale, { maximumFractionDigits: 0 });

export function formatCount(value: number): string {
  return counts.format(value);
}
