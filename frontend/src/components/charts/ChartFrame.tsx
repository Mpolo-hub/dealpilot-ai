// Accessible frame for every chart (spec 007 D12, section 10): a figure with a title and
// a visually hidden data table as the text alternative.
import type { ReactNode } from "react";

import { text } from "../../text/en";

export interface ChartDatum {
  label: string;
  value: number;
  display: string;
}

export function ChartFrame({ title, data, valueHeader, children }: {
  title: string; data: ChartDatum[]; valueHeader: string; children: ReactNode;
}) {
  return (
    <figure className="chart-figure">
      <figcaption className="visually-hidden">{title}</figcaption>
      {children}
      {/* The hidden wrapper is a div: a table ignores a 1 px box, so a hidden 1,096-row
          table would otherwise keep its full height and stretch the page. */}
      <div className="visually-hidden">
        <table>
          <caption>{`${text.common.chartDescription}: ${title}`}</caption>
          <thead>
            <tr><th scope="col">{text.common.dataTable}</th><th scope="col">{valueHeader}</th></tr>
          </thead>
          <tbody>
            {data.map((d) => (
              <tr key={d.label}><th scope="row">{d.label}</th><td>{d.display}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </figure>
  );
}
