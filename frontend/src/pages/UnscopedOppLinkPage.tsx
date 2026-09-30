import { Link, useParams } from "react-router-dom";

import { EmptyState } from "../components/opps/LoadingStates";

/**
 * What a bare `/opps/<slug>` link shows. The path predates workspaces, and
 * it used to redirect to the viewer's most recent workspace — a GUESS, and
 * a wrong one as soon as two workspaces hold an opp with the same slug
 * (`spark` and `dimagi-team` both have `spark-facilitator`): the reader
 * silently landed on the other workspace's opp. An opp link has to name
 * its workspace, so this one is a dead end that says so and points at the
 * opp list rather than picking for them.
 */
export default function UnscopedOppLinkPage() {
  const { slug = "" } = useParams();
  return (
    <EmptyState
      title="This link doesn't say which workspace the opp is in"
      description={
        `Links to an opp include its workspace (/w/<workspace>/opps/${slug}), ` +
        "because opps in different workspaces can share a name. " +
        "Open it from your workspace's opp list instead."
      }
      action={
        <Link to="/opps" className="text-sm font-medium text-primary hover:underline">
          Go to your opps
        </Link>
      }
    />
  );
}
