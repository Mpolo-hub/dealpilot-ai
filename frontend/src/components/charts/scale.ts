// Axis helpers shared by the SVG charts (kept apart from components for fast refresh).

/**
 * A round axis maximum, at least the data maximum, whose quarter (four gridlines) is also
 * round: 1, 2, 4 or 8 times a power of ten (so steps of 0.25, 0.5, 1 or 2 units).
 */
export function niceMax(value: number): number {
  if (value <= 0) return 1;
  const power = 10 ** Math.floor(Math.log10(value));
  for (const step of [1, 2, 4, 8, 10]) {
    if (step * power >= value) return step * power;
  }
  return 10 * power;
}
