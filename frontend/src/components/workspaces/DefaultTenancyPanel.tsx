import { useEffect, useState } from "react";

import { Button } from "canopy-ui/ui";

/**
 * Where a NEW opp in this workspace keeps its assets in each system ACE
 * writes to (apps/opps/tenancy.py). Copied into each opp when it is created;
 * changing it never rewrites existing opps. ACE locks a session to an opp's
 * tenancy (bin/ace-bind), so this decides where ACE may write.
 *
 * OCS is deliberately absent: reviewers get no OCS account (OCS permissions
 * are team-wide), so a workspace has no OCS team to name here.
 */
export type Tenancy = {
  hq_domain?: string;
  connect_pm_org?: string;
  connect_holding_org?: string;
  labs_allowed_domains?: string[];
  [key: string]: unknown;
};

const TEXT_FIELDS = [
  { key: "hq_domain", label: "CommCare HQ project space", placeholder: "connect-ace-spark" },
  { key: "connect_pm_org", label: "Connect program-manager org", placeholder: "org slug" },
  { key: "connect_holding_org", label: "Connect holding org", placeholder: "org slug" },
] as const;

type Draft = Record<(typeof TEXT_FIELDS)[number]["key"] | "labs_allowed_domains", string>;

function toDraft(t: Tenancy): Draft {
  return {
    hq_domain: t.hq_domain ?? "",
    connect_pm_org: t.connect_pm_org ?? "",
    connect_holding_org: t.connect_holding_org ?? "",
    labs_allowed_domains: (t.labs_allowed_domains ?? []).join(", "),
  };
}

/** The PATCH body: blank clears a field (null), unchanged fields are omitted. */
export function tenancyPatch(before: Tenancy, draft: Draft): Record<string, unknown> {
  const patch: Record<string, unknown> = {};
  for (const { key } of TEXT_FIELDS) {
    const next = draft[key].trim();
    if (next !== (before[key] ?? "")) patch[key] = next || null;
  }
  const domains = draft.labs_allowed_domains
    .split(/[,\s]+/)
    .map((d) => d.trim())
    .filter(Boolean);
  const prev = before.labs_allowed_domains ?? [];
  if (domains.join(",") !== prev.join(",")) {
    patch.labs_allowed_domains = domains.length ? domains : null;
  }
  return patch;
}

export function DefaultTenancyPanel({
  tenancy,
  canEdit,
  onSave,
}: {
  tenancy: Tenancy;
  canEdit: boolean;
  onSave: (patch: Record<string, unknown>) => Promise<void>;
}) {
  const [draft, setDraft] = useState<Draft>(() => toDraft(tenancy));
  const [msg, setMsg] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const tenancyKey = JSON.stringify(tenancy);

  useEffect(() => {
    setDraft(toDraft(tenancy));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed on content
  }, [tenancyKey]);

  async function handleSave() {
    const patch = tenancyPatch(tenancy, draft);
    if (Object.keys(patch).length === 0) {
      setMsg("No changes.");
      return;
    }
    setSaving(true);
    setMsg(null);
    try {
      await onSave(patch);
      setMsg("Saved. New opps start with this; existing opps are unchanged.");
    } catch (e) {
      setMsg(String((e as Error).message));
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="mt-8">
      <h2 className="text-lg font-medium text-foreground">Default tenancy</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        Where a new opp in this workspace keeps its assets. ACE may only write
        to these when it works on the opp. Changing this does not move existing
        opps.
      </p>
      <dl className="mt-3 grid grid-cols-[200px_1fr] items-center gap-x-3 gap-y-2 text-sm">
        {TEXT_FIELDS.map(({ key, label, placeholder }) => (
          <div key={key} className="contents">
            <dt className="text-muted-foreground">
              <label htmlFor={`tenancy-${key}`}>{label}</label>
            </dt>
            <dd>
              {canEdit ? (
                <input
                  id={`tenancy-${key}`}
                  type="text"
                  placeholder={placeholder}
                  value={draft[key]}
                  onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}
                  className="w-full rounded border border-input bg-background px-3 py-1.5 font-mono text-sm text-foreground"
                />
              ) : (
                <span className="font-mono text-foreground">{draft[key] || "not set"}</span>
              )}
            </dd>
          </div>
        ))}
        <dt className="text-muted-foreground">
          <label htmlFor="tenancy-labs_allowed_domains">Labs allowed domains</label>
        </dt>
        <dd>
          {canEdit ? (
            <input
              id="tenancy-labs_allowed_domains"
              type="text"
              placeholder="@sparkmicrogrants.org"
              value={draft.labs_allowed_domains}
              onChange={(e) => setDraft({ ...draft, labs_allowed_domains: e.target.value })}
              className="w-full rounded border border-input bg-background px-3 py-1.5 font-mono text-sm text-foreground"
            />
          ) : (
            <span className="font-mono text-foreground">
              {draft.labs_allowed_domains || "not set"}
            </span>
          )}
        </dd>
      </dl>
      {canEdit && (
        <div className="mt-3 flex items-center gap-3">
          <Button onClick={handleSave} disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </Button>
          {msg && <p className="text-sm text-muted-foreground">{msg}</p>}
        </div>
      )}
    </section>
  );
}
