/**
 * `GET …/lineage` payloads for a clone of a FRESH run — the shape of
 * spark/spark-facilitator/20261004-1706 (copied from dimagi-team's independent
 * run, with the Connect rows re-minted as `<id>-dimagi-team` → `<id>`), built
 * from `_fresh_chain()` in `apps/opps/tests/test_decision_lineage.py`.
 * Regenerate rather than hand-edit: `scripts/regen_lineage_fixtures.py`.
 */
import type { DecisionLineage } from "@/api/lineage";

export const FRESH_CLONE_MEMBER: DecisionLineage = {
  "schema_version": 1,
  "scope": "lineage",
  "chain": [
    {
      "position": 0,
      "via": "cloned",
      "at_phase": "",
      "stage": "",
      "date": "2026-10-04",
      "copied_date": "2026-10-06",
      "readable": true,
      "workbench_url": "/ace/w/spark/opps/spark-facilitator/runs/20261004-1706",
      "summary_url": "/ace/opps/spark/spark-facilitator/runs/20261004-1706/summary",
      "workspace": "spark",
      "opp": "spark-facilitator",
      "run_id": "20261004-1706",
      "decisions": 7
    },
    {
      "position": 1,
      "via": "",
      "at_phase": "",
      "stage": "",
      "date": "2026-10-04",
      "copied_date": "",
      "readable": true,
      "workbench_url": null,
      "summary_url": null,
      "workspace": "dimagi-team",
      "opp": "spark-facilitator",
      "run_id": "20261004-1706",
      "decisions": 4
    }
  ],
  "origins": {
    "working-language": {
      "kind": "decided",
      "from_position": 1,
      "from_run": "20261004-1706",
      "from_date": "2026-10-04",
      "in_position": 1,
      "in_run": "20261004-1706",
      "in_date": "2026-10-04",
      "on_copy": false,
      "previous_value": "",
      "by": "",
      "at": ""
    },
    "gps-per-meeting-capture": {
      "kind": "decided",
      "from_position": 1,
      "from_run": "20261004-1706",
      "from_date": "2026-10-04",
      "in_position": 1,
      "in_run": "20261004-1706",
      "in_date": "2026-10-04",
      "on_copy": false,
      "previous_value": "",
      "by": "",
      "at": ""
    },
    "connect-rule-one-paid-per-worker-per-day": {
      "kind": "decided",
      "from_position": 1,
      "from_run": "20261004-1706",
      "from_date": "2026-10-04",
      "in_position": 1,
      "in_run": "20261004-1706",
      "in_date": "2026-10-04",
      "on_copy": false,
      "previous_value": "",
      "by": "",
      "at": ""
    },
    "connect-opportunity": {
      "kind": "changed",
      "from_position": 1,
      "from_run": "20261004-1706",
      "from_date": "2026-10-04",
      "in_position": 0,
      "in_run": "20261004-1706",
      "in_date": "2026-10-04",
      "on_copy": true,
      "previous_value": "dimagi-ace-pm opportunity 812",
      "by": "",
      "at": ""
    },
    "wo-fixed-costs-fee-structure": {
      "kind": "new",
      "from_position": null,
      "from_run": "",
      "from_date": "",
      "in_position": 0,
      "in_run": "20261004-1706",
      "in_date": "2026-10-04",
      "on_copy": false,
      "previous_value": "",
      "by": "",
      "at": ""
    }
  },
  "counts": {
    "new": 1,
    "decided": 3,
    "carried": 0,
    "changed": 1,
    "reaffirmed": 0,
    "human": 0
  },
  "histories": {
    "working-language": [
      {
        "workspace": "dimagi-team",
        "opp": "spark-facilitator",
        "run_id": "20261004-1706",
        "date": "2026-10-04",
        "in_lineage": true,
        "readable": true,
        "found": true,
        "row_id": "working-language",
        "match": "id",
        "value": "English",
        "plain_value": "",
        "status": "ai-default",
        "superseded": false,
        "by": "",
        "at": "",
        "reason": "",
        "copied_to": [
          {
            "workspace": "spark",
            "date": "2026-10-06"
          }
        ],
        "current": true,
        "linked": false
      }
    ],
    "gps-per-meeting-capture": [
      {
        "workspace": "dimagi-team",
        "opp": "spark-facilitator",
        "run_id": "20261004-1706",
        "date": "2026-10-04",
        "in_lineage": true,
        "readable": true,
        "found": true,
        "row_id": "gps-per-meeting-capture",
        "match": "id",
        "value": "Captured with accuracy, optional, advisory only",
        "plain_value": "",
        "status": "ai-default",
        "superseded": false,
        "by": "",
        "at": "",
        "reason": "",
        "copied_to": [
          {
            "workspace": "spark",
            "date": "2026-10-06"
          }
        ],
        "current": true,
        "linked": false
      }
    ],
    "connect-rule-one-paid-per-worker-per-day": [
      {
        "workspace": "dimagi-team",
        "opp": "spark-facilitator",
        "run_id": "20261004-1706",
        "date": "2026-10-04",
        "in_lineage": true,
        "readable": true,
        "found": true,
        "row_id": "connect-rule-one-paid-per-worker-per-day",
        "match": "id",
        "value": "Connect payment unit limit",
        "plain_value": "",
        "status": "ai-default",
        "superseded": false,
        "by": "",
        "at": "",
        "reason": "",
        "copied_to": [
          {
            "workspace": "spark",
            "date": "2026-10-06"
          }
        ],
        "current": true,
        "linked": false
      }
    ],
    "connect-opportunity": [
      {
        "workspace": "dimagi-team",
        "opp": "spark-facilitator",
        "run_id": "20261004-1706",
        "date": "2026-10-04",
        "in_lineage": true,
        "readable": true,
        "found": true,
        "row_id": "connect-opportunity",
        "match": "id",
        "value": "dimagi-ace-pm opportunity 812",
        "plain_value": "",
        "status": "ai-default",
        "superseded": false,
        "by": "",
        "at": "",
        "reason": "",
        "linked": false
      },
      {
        "workspace": "spark",
        "opp": "spark-facilitator",
        "run_id": "20261004-1706",
        "date": "2026-10-04",
        "in_lineage": true,
        "readable": true,
        "found": true,
        "row_id": "connect-opportunity",
        "match": "id",
        "value": "spark-pm opportunity 905",
        "plain_value": "",
        "status": "ai-default",
        "superseded": false,
        "by": "",
        "at": "",
        "reason": "",
        "current": true,
        "linked": true
      }
    ],
    "wo-fixed-costs-fee-structure": [
      {
        "workspace": "dimagi-team",
        "opp": "spark-facilitator",
        "run_id": "20261004-1706",
        "date": "2026-10-04",
        "in_lineage": true,
        "readable": true,
        "found": false,
        "by": "",
        "linked": false
      },
      {
        "workspace": "spark",
        "opp": "spark-facilitator",
        "run_id": "20261004-1706",
        "date": "2026-10-04",
        "in_lineage": true,
        "readable": true,
        "found": true,
        "row_id": "wo-fixed-costs-fee-structure",
        "match": "id",
        "value": "Per-meeting fee only",
        "plain_value": "",
        "status": "ai-default",
        "superseded": false,
        "by": "",
        "at": "",
        "reason": "",
        "current": true,
        "linked": true
      }
    ]
  },
  "viewer": {
    "is_member": true
  }
};
export const FRESH_CLONE_OUTSIDER: DecisionLineage = {
  "schema_version": 1,
  "scope": "lineage",
  "chain": [
    {
      "position": 0,
      "via": "cloned",
      "at_phase": "",
      "stage": "",
      "date": "2026-10-04",
      "copied_date": "2026-10-06",
      "readable": true,
      "workbench_url": null,
      "summary_url": null,
      "workspace": null,
      "opp": null,
      "run_id": null,
      "decisions": null
    },
    {
      "position": 1,
      "via": "",
      "at_phase": "",
      "stage": "",
      "date": "2026-10-04",
      "copied_date": "",
      "readable": true,
      "workbench_url": null,
      "summary_url": null,
      "workspace": null,
      "opp": null,
      "run_id": null,
      "decisions": null
    }
  ],
  "origins": {
    "working-language": {
      "kind": "decided",
      "from_position": 1,
      "from_run": null,
      "from_date": "2026-10-04",
      "in_position": 1,
      "in_run": null,
      "in_date": "2026-10-04",
      "on_copy": false,
      "previous_value": "",
      "by": "",
      "at": ""
    },
    "gps-per-meeting-capture": {
      "kind": "decided",
      "from_position": 1,
      "from_run": null,
      "from_date": "2026-10-04",
      "in_position": 1,
      "in_run": null,
      "in_date": "2026-10-04",
      "on_copy": false,
      "previous_value": "",
      "by": "",
      "at": ""
    },
    "connect-rule-one-paid-per-worker-per-day": {
      "kind": "decided",
      "from_position": 1,
      "from_run": null,
      "from_date": "2026-10-04",
      "in_position": 1,
      "in_run": null,
      "in_date": "2026-10-04",
      "on_copy": false,
      "previous_value": "",
      "by": "",
      "at": ""
    },
    "connect-opportunity": {
      "kind": "changed",
      "from_position": 1,
      "from_run": null,
      "from_date": "2026-10-04",
      "in_position": 0,
      "in_run": null,
      "in_date": "2026-10-04",
      "on_copy": true,
      "previous_value": "",
      "by": "",
      "at": ""
    },
    "wo-fixed-costs-fee-structure": {
      "kind": "new",
      "from_position": null,
      "from_run": null,
      "from_date": "",
      "in_position": 0,
      "in_run": null,
      "in_date": "2026-10-04",
      "on_copy": false,
      "previous_value": "",
      "by": "",
      "at": ""
    }
  },
  "counts": {
    "new": 1,
    "decided": 3,
    "carried": 0,
    "changed": 1,
    "reaffirmed": 0,
    "human": 0
  },
  "histories": {},
  "viewer": {
    "is_member": false
  }
};
