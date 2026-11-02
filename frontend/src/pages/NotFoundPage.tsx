import { Link } from "react-router";

import { PageHeader } from "../components/ui";
import { text } from "../text/en";

export function NotFoundPage() {
  return (
    <>
      <PageHeader title={text.notFound.title} subtitle={text.notFound.body} />
      <Link to="/" className="text-link">{text.notFound.back}</Link>
    </>
  );
}
