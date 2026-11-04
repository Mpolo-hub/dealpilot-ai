import { Link } from "react-router";

import { dashboardPath } from "../demo";

import { PageHeader } from "../components/ui";
import { text } from "../text/en";

export function NotFoundPage() {
  return (
    <>
      <PageHeader title={text.notFound.title} subtitle={text.notFound.body} />
      <Link to={dashboardPath()} className="text-link">{text.notFound.back}</Link>
    </>
  );
}
