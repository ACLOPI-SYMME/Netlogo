"""A2 measurement: is the throughput limited by the product arrival rule?

Go creates a product when, at the moment it evaluates the arrival rule (after the machines,
the movement of products and gates, and PotentialFields of that tick):
    Simulated.Time mod 100 <= 0.2                    (time window)
    and count products with [Product.State != "death"] < 10    (fewer than 10 active)
    and no product in the entry zone x 90..115, y 80..110      (zone free)
Each crossing of a multiple of 100 time units is an arrival opportunity. For every opportunity
this script records whether it produced a product or was lost, and why:
- window skipped: no tick of the interval had Simulated.Time mod 100 <= 0.2;
- 10 active products;
- entry zone occupied, by what: products of M1 operation O8 (new product on the loading
  segment, waiting at or processed by M1), of O9 (back to M1 for the last operation), leaving
  M1 after O8, or other products passing through the zone;
- combinations. For skipped windows it also records what the other two conditions were at the
  first tick of the interval (would the opportunity have been lost anyway?).

The model is not modified: a copy of model/Paper.nlogo with recording calls around the arrival
rule is written to a temporary folder. The calls only read the state, inside
with-local-randomness. Every instrumented run is checked against a normal run with the same
seed (KPIs and Events hash must be identical); otherwise the script fails.

Usage (from the repository root):
    python scripts/a2/measure_arrivals.py                      # rule 3 seeds 42 7 123, rule 1 seed 42
    python scripts/a2/measure_arrivals.py --runs 3:42 --horizon 10000
Results: results/a2/arrivals_r<rule>_s<seed>.json and results/a2/arrivals_summary.md
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # scripts/

from compare_baseline import sha256 as content_sha256  # noqa: E402

from aclopi.sim import SimulationSession  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
MODEL = REPO_ROOT / "model" / "Paper.nlogo"
OUTPUT_DIR = REPO_ROOT / "results" / "a2"
DEFAULT_RUNS = ["3:42", "3:7", "3:123", "1:42"]

# Instr.Before goes right after the zone count (just before the arrival `if`), Instr.After right
# after the creation block (before `let logs`, the next statement of Go).
ARRIVAL_ANCHOR = "    let counter count products with [xcor >= 90 and xcor <= 115 and ycor >= 80 and ycor <= 110]\n"
INSTRUMENTED_ARRIVAL = ARRIVAL_ANCHOR + "    Instr.Before counter\n"
AFTER_ANCHOR = "  let logs  Interval.logs\n"
INSTRUMENTED_AFTER = "  Instr.After\n" + AFTER_ANCHOR
GLOBALS_ANCHOR = "globals [\n"
INSTRUMENT_GLOBALS = (
    "globals [\n"
    "  instr-rows instr-last-interval instr-new-interval? instr-products-before\n"
    "  instr-ticks instr-wip-sum instr-full-ticks instr-zone-ticks instr-window-ticks instr-created instr-anomalies\n"
)
SECTION_SEPARATOR = "@#$#@#$#@"
INSTRUMENT_PROCEDURES = """
; ===== Arrival instrumentation (scripts/a2/measure_arrivals.py). Read-only, inside with-local-randomness. =====

to Instr.Before [#counter]
  with-local-randomness [
    if not is-list? instr-rows [set instr-rows []]
    let active count products with [Product.State != "death"]
    set instr-ticks instr-ticks + 1
    set instr-wip-sum instr-wip-sum + active
    if (active >= 10) [set instr-full-ticks instr-full-ticks + 1]
    if (#counter > 0) [set instr-zone-ticks instr-zone-ticks + 1]
    let window? (simulated.time mod 100 <= 0.2)
    if window? [set instr-window-ticks instr-window-ticks + 1]
    let interval floor (simulated.time / 100)
    set instr-new-interval? (interval != instr-last-interval)
    if instr-new-interval? [
      set instr-last-interval interval
      let zone map [p -> Instr.Zone.Category p] sort products with [xcor >= 90 and xcor <= 115 and ycor >= 80 and ycor <= 110]
      set instr-rows lput (list interval ticks simulated.time window? active #counter zone false) instr-rows
    ]
    if (window? and not instr-new-interval?) [set instr-anomalies instr-anomalies + 1]
    set instr-products-before count products
  ]
end

to Instr.After
  with-local-randomness [
    if (count products > instr-products-before) [
      set instr-created instr-created + 1
      ifelse instr-new-interval?
        [set instr-rows lput (replace-item 7 last instr-rows true) but-last instr-rows]
        [set instr-anomalies instr-anomalies + 1]
    ]
  ]
end

to-report Instr.Zone.Category [#p]
  ; at-M1-*: on the M1 station (sensor 158); to-M1-*: heading to M1 elsewhere in the zone.
  report [(ifelse-value
    (xcor = [xcor] of sensor 158 and ycor = [ycor] of sensor 158) [
      (ifelse-value
        (length ProductRealStart > length ProductRealCompletion) [(word "at-M1-processing-" Next.Product.Operation)]
        (Heading.Workstation = "M1") [(word "at-M1-waiting-" Next.Product.Operation)]
        ["at-M1-leaving"])
    ]
    (Heading.Workstation = "M1") [(word "to-M1-" Next.Product.Operation)]
    ["passing"])] of #p
end

to-report Instr.Report
  let result ""
  with-local-randomness [
    set result json-obj (list
      (list "rows" json-any instr-rows)
      (list "ticks" json-num instr-ticks)
      (list "wip_sum" json-num instr-wip-sum)
      (list "full_ticks" json-num instr-full-ticks)
      (list "zone_ticks" json-num instr-zone-ticks)
      (list "window_ticks" json-num instr-window-ticks)
      (list "created" json-num instr-created)
      (list "anomalies" json-num instr-anomalies))
  ]
  report result
end
"""

# Zone categories -> what occupies the entry zone.
ZONE_GROUPS = {"O8": "M1 O8 (loading/waiting/processing)", "O9": "M1 O9 (return/waiting/processing)",
               "leaving": "leaving M1", "passing": "other (passing)"}


def zone_group(category: str) -> str:
    if category == "at-M1-leaving":
        return ZONE_GROUPS["leaving"]
    if category == "passing":
        return ZONE_GROUPS["passing"]
    if category.endswith("O8"):
        return ZONE_GROUPS["O8"]
    if category.endswith("O9"):
        return ZONE_GROUPS["O9"]
    return f"other ({category})"


def instrumented_model(target_dir: Path) -> Path:
    text = MODEL.read_text(encoding="utf-8")
    for anchor in (ARRIVAL_ANCHOR, AFTER_ANCHOR, GLOBALS_ANCHOR):
        if text.count(anchor) != 1:
            raise RuntimeError(f"anchor not found exactly once in {MODEL}: {anchor!r}")
    text = (text.replace(ARRIVAL_ANCHOR, INSTRUMENTED_ARRIVAL).replace(AFTER_ANCHOR, INSTRUMENTED_AFTER)
            .replace(GLOBALS_ANCHOR, INSTRUMENT_GLOBALS))
    code, rest = text.split(SECTION_SEPARATOR, 1)
    path = target_dir / "Paper_instrumented.nlogo"
    path.write_bytes((code + INSTRUMENT_PROCEDURES + SECTION_SEPARATOR + rest).encode("utf-8"))  # keep LF
    return path


def run_once(session: SimulationSession, rule: int, seed: int, horizon: int) -> dict[str, Any]:
    session.setup(seed=seed, rule=rule, horizon_ticks=horizon, fixed_product_sequence=False)  # original model
    session.run_to_end()
    results = session.directory / "Results"
    return {
        "kpis": session.kpis().as_dict(),
        "events_sha256": content_sha256(results / "Events" / f"Event_100_Sto_R {rule}_0.csv"),
    }


def classify(row: list[Any]) -> tuple[str, str]:
    """(outcome, cause) of one opportunity row [interval tick time window? active counter zone created?]."""
    _, _, _, window, active, counter, zone, created = row
    if created:
        return "created", "created"
    blockers = []
    if active >= 10:
        blockers.append("10 active")
    if counter > 0:
        blockers.append("zone: " + " + ".join(sorted({zone_group(c) for c in zone})))
    if not window:
        return "lost", "window skipped" + (" (also " + " and ".join(blockers) + ")" if blockers else " (only cause)")
    return "lost", " and ".join(blockers) if blockers else "UNEXPLAINED"


def summarize(rule: int, seed: int, data: dict[str, Any]) -> dict[str, Any]:
    rows = data["rows"]
    causes = Counter(classify(r)[1] for r in rows)
    lost = [r for r in rows if not r[7]]
    evaluated_lost = [r for r in lost if r[3]]
    zone_lost = [r for r in evaluated_lost if r[5] > 0]
    zone_groups = Counter(g for r in zone_lost for g in {zone_group(c) for c in r[6]})
    return {
        "rule": rule, "seed": seed,
        "opportunities": len(rows),
        "created": sum(1 for r in rows if r[7]),
        "lost": len(lost),
        "window_skipped": sum(1 for r in lost if not r[3]),
        "window_skipped_only_cause": causes.get("window skipped (only cause)", 0),
        "lost_10_active_any": sum(1 for r in evaluated_lost if r[4] >= 10),
        "lost_zone_any": len(zone_lost),
        "lost_zone_only": sum(1 for r in evaluated_lost if r[5] > 0 and r[4] < 10),
        "lost_10_active_only": sum(1 for r in evaluated_lost if r[4] >= 10 and r[5] == 0),
        "lost_both": sum(1 for r in evaluated_lost if r[4] >= 10 and r[5] > 0),
        "zone_occupants_in_losses": dict(zone_groups),
        "causes": dict(causes.most_common()),
        "mean_wip": data["wip_sum"] / data["ticks"],
        "pct_time_10_active": 100 * data["full_ticks"] / data["ticks"],
        "pct_time_zone_occupied": 100 * data["zone_ticks"] / data["ticks"],
        "window_ticks": data["window_ticks"],
        "anomalies": data["anomalies"],
    }


def markdown(summaries: list[dict[str, Any]], horizon: int) -> str:
    lines = [f"# Arrival opportunities ({horizon} ticks, Stochastic)", "",
             "| run | opportunities | created | lost | window skipped (only cause) | 10 active only | zone only | 10 active + zone | mean WIP | % time 10 active | % time zone occupied |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in summaries:
        lines.append(
            f"| R{s['rule']} s{s['seed']} | {s['opportunities']} | {s['created']} | {s['lost']} | "
            f"{s['window_skipped']} ({s['window_skipped_only_cause']}) | {s['lost_10_active_only']} | {s['lost_zone_only']} | "
            f"{s['lost_both']} | {s['mean_wip']:.2f} | {s['pct_time_10_active']:.1f} | {s['pct_time_zone_occupied']:.1f} |")
    lines += ["", "## Causes in detail (every opportunity)", ""]
    for s in summaries:
        lines.append(f"### R{s['rule']} s{s['seed']}")
        lines += [f"- {cause}: {n}" for cause, n in s["causes"].items()]
        lines.append(f"- what occupied the zone in the evaluated losses: {s['zone_occupants_in_losses']}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    logging.basicConfig(level=logging.WARNING)
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--runs", nargs="+", default=DEFAULT_RUNS, help="rule:seed pairs")
    parser.add_argument("--horizon", type=int, default=100000)
    args = parser.parse_args()
    runs = [tuple(int(x) for x in r.split(":")) for r in args.runs]

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    summaries = []
    with tempfile.TemporaryDirectory(prefix="aclopi_arrivals_") as tmp:
        model = instrumented_model(Path(tmp))
        with SimulationSession("arrivals_normal") as normal, SimulationSession("arrivals_instr", model_path=model) as instr:
            for rule, seed in runs:
                reference = run_once(normal, rule, seed, args.horizon)
                measured = run_once(instr, rule, seed, args.horizon)
                valid = reference == measured
                data = json.loads(str(instr.link.report("Instr.Report")))
                summary = summarize(rule, seed, data)
                summary["valid"] = valid
                summary["finished"] = measured["kpis"]["finished"]
                print(f"R{rule} s{seed}: instrumented run identical to normal run (KPIs, Events): {valid}; "
                      f"opportunities {summary['opportunities']}, created {summary['created']}, "
                      f"anomalies {summary['anomalies']}", flush=True)
                if not valid:
                    print(f"  normal: {reference}\n  instrumented: {measured}")
                    return 1
                (OUTPUT_DIR / f"arrivals_r{rule}_s{seed}.json").write_text(
                    json.dumps({"summary": summary, **data}, indent=1), encoding="utf-8")
                summaries.append(summary)
    report = markdown(summaries, args.horizon)
    (OUTPUT_DIR / "arrivals_summary.md").write_text(report + "\n", encoding="utf-8")
    print()
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
