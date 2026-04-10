import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { listOpps } from "../../api/opps";
import type { OppCard } from "../../api/types";

export function OppSidebar() {
  const [opps, setOpps] = useState<OppCard[]>([]);
  const [filter, setFilter] = useState("");
  const { slug: currentSlug } = useParams();

  useEffect(() => {
    listOpps().then(setOpps).catch(() => setOpps([]));
  }, []);

  const filtered = opps.filter(
    (o) =>
      !filter ||
      o.slug.toLowerCase().includes(filter.toLowerCase()) ||
      o.display_name.toLowerCase().includes(filter.toLowerCase()),
  );

  return (
    <div className="flex h-full flex-col">
      <div className="px-3 pt-3 text-[10px] uppercase tracking-wider text-muted-foreground">
        Opps · {opps.length}
      </div>
      <div className="px-2 py-2">
        <input
          type="text"
          placeholder="Filter…"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="w-full rounded border border-border bg-card px-2 py-1 text-xs text-foreground placeholder:text-muted-foreground focus:border-ring focus:outline-none"
        />
      </div>
      <div className="flex-1 overflow-y-auto">
        {filtered.map((o) => {
          const isActive = o.slug === currentSlug;
          return (
            <Link
              key={o.slug}
              to={`/opps/${o.slug}`}
              className={`block border-l-2 px-3 py-2 text-xs hover:bg-accent ${
                isActive
                  ? "border-primary bg-accent text-foreground"
                  : "border-transparent text-muted-foreground"
              }`}
            >
              <div className="flex items-center gap-2">
                <span className="font-semibold">{o.display_name || o.slug}</span>
              </div>
              <div className="mt-0.5 text-[10px] text-muted-foreground">
                {o.current_step ?? "—"}
              </div>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
