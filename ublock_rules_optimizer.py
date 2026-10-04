#!/usr/bin/env python3
"""
ublock_rules_optimizer.py - shrink a uBlock Origin "My rules" (dynamic filtering) export.

Two phases:

  1. PRUNE (behaviour-preserving, always on)
     Removes a rule only if a simulation of uBO's rule resolution proves that every
     request resolves exactly as before. Catches exact duplicates, per-site rules
     already covered by a global/parent-domain rule, and rules covered by a parent
     destination (e.g. `* cdnjs.cloudflare.com` when `* cloudflare.com` exists).

  2. PROMOTE / HOIST (intentionally loosens scope - you control it)
     --min-sources N        Promote `site dest type noop` to `* dest type noop` when N or more
                            distinct sites (registrable domains) use it. Default 5. 0 disables.
     --hoist-subdomains M   If M+ subdomains of one site share a rule (a.x.com, b.x.com, ...),
                            replace them with a single rule on x.com. Default 0 (off).
     After either, PRUNE runs again to delete the now-redundant per-site rules.

Usage:
    python3 ublock_rules_optimizer.py my-rules.txt                    # writes my-rules.optimized.txt
    python3 ublock_rules_optimizer.py my-rules.txt --dry-run          # report only
    python3 ublock_rules_optimizer.py my-rules.txt --min-sources 3 --hoist-subdomains 3
    python3 ublock_rules_optimizer.py my-rules.txt --exclude example-tracker.com
    python3 ublock_rules_optimizer.py my-rules.txt --report changes.txt

Import the result via uBlock Origin > Dashboard > My rules > Import from file, then Commit.
Keep a copy of the original export; the script never modifies its input.
"""
import argparse
import sys
from collections import defaultdict
from pathlib import Path

ACTIONS = {"allow", "block", "noop"}
SENTINEL = "unseen-host.invalid"  # stands in for "any site that has no rules of its own"

# Rough public-suffix handling so www.foo.com.au -> foo.com.au (no external dependency).
SECOND_LEVEL_SUFFIXES = {
    "com.au", "net.au", "org.au", "edu.au", "gov.au", "id.au", "asn.au",
    "co.uk", "org.uk", "ac.uk", "gov.uk", "me.uk", "co.nz", "org.nz", "net.nz",
    "govt.nz", "co.jp", "ne.jp", "or.jp", "co.in", "co.za", "com.br", "com.cn",
    "com.hk", "com.sg", "com.tw", "com.mx", "com.ar", "com.tr", "co.kr",
}

# Destinations never auto-promoted to global: broad platforms that also serve ads/tracking,
# where "allow everywhere" is rarely what you want. Edit freely or use --no-default-excludes.
DEFAULT_EXCLUDES = {
    "google.com", "facebook.com", "facebook.net", "fbcdn.net", "twitter.com", "x.com",
    "doubleclick.net", "google-analytics.com", "googlesyndication.com",
    "googleadservices.com", "adnxs.com", "criteo.com", "taboola.com", "outbrain.com",
    "hotjar.com", "amazon.com", "microsoft.com", "linkedin.com", "tiktok.com",
}


# --------------------------------------------------------------------------- helpers
def registrable(host):
    labels = host.split(".")
    if len(labels) <= 2:
        return host
    if ".".join(labels[-2:]) in SECOND_LEVEL_SUFFIXES and len(labels) >= 3:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def chain(host):
    """host, parent, grandparent... (never '*')."""
    while True:
        yield host
        i = host.find(".")
        if i < 0:
            return
        host = host[i + 1:]


def is_descendant(host, ancestor):
    return host == ancestor or host.endswith("." + ancestor)


# ------------------------------------------------------------------- parse / write
def parse(path):
    header, other, rules, dupes = [], [], {}, 0
    for raw in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if parts[0].endswith(":"):                      # switches e.g. "no-csp-reports: * true"
            header.append(line)
        elif (len(parts) == 4 and parts[3] in ACTIONS
              and "/" not in parts[0] and "/" not in parts[1]):
            key = (parts[0], parts[1], parts[2])
            if key in rules:
                dupes += 1
            rules[key] = parts[3]
        else:                                           # URL rules, comments, anything unknown
            other.append(line)
    return header, other, rules, dupes


def write(path, header, other, rules):
    def sort_key(k):
        s, d, t = k
        return (s != "*", s if s != "*" else "", d != "*", d, t != "*", t)
    lines = list(header)
    lines += [f"{s} {d} {t} {rules[(s, d, t)]}" for (s, d, t) in sorted(rules, key=sort_key)]
    lines += other
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


# ----------------------------------------------------- uBO resolution (per type key)
# uBO checks specific destinations before the wildcard destination; for a given
# destination it walks the source from most to least specific, then '*'. Different
# type keys ('*', '3p', '3p-frame', ...) are resolved independently, and cross-type
# precedence is the same before and after a removal, so we only need to prove that
# each (key, destination-kind) result is unchanged.
def _by_source(rules, src, dest, key):
    for s in chain(src):
        a = rules.get((s, dest, key))
        if a:
            return a
    return rules.get(("*", dest, key))


def resolve_specific(rules, src, dest, key):
    for d in chain(dest):
        a = _by_source(rules, src, d, key)
        if a:
            return a
    return None


def resolve_any(rules, src, key):
    return _by_source(rules, src, "*", key)


def probes(host, universe):
    if host == "*":
        return set(universe) | {SENTINEL}
    return {host} | {h for h in universe if is_descendant(h, host)}


def _snapshot(rules, key, S, D):
    s, d, k = key
    if d == "*":
        return [resolve_any(rules, x, k) for x in sorted(S)]
    return [resolve_specific(rules, x, y, k) for x in sorted(S) for y in sorted(D)]


def prune(rules):
    """Delete provably-redundant rules in place. Returns [(rule, action, reason)]."""
    sources = {s for (s, _, _) in rules if s != "*"}
    dests = {d for (_, d, _) in rules if d != "*"}
    removed = []
    order = sorted(rules, key=lambda k: (-k[0].count("."), -k[1].count("."), k))
    for key in order:
        if key not in rules:
            continue
        s, d, k = key
        if s == "*" and d == "*":
            continue                                    # never touch the global defaults
        S = probes(s, sources)
        D = probes(d, dests) if d != "*" else set()
        before = _snapshot(rules, key, S, D)
        action = rules.pop(key)
        if before == _snapshot(rules, key, S, D):
            if d != "*" and s != "*" and ("*", d, k) in rules:
                why = "covered by global rule"
            elif any((a, d, k) in rules for a in list(chain(s))[1:]):
                why = "covered by parent-domain rule"
            elif d != "*" and any((s, a, k) in rules for a in list(chain(d))[1:]):
                why = "covered by parent-destination rule"
            else:
                why = "redundant"
            removed.append((key, action, why))
        else:
            rules[key] = action
    return removed


# ----------------------------------------------------------------- promote / hoist
def promote_global(rules, min_sources, excludes):
    groups = defaultdict(set)
    for (s, d, k), a in rules.items():
        if s != "*" and d != "*" and a in ("noop", "allow"):
            groups[(d, k, a)].add(registrable(s))
    promoted, skipped = [], []
    for (d, k, a), sites in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        if len(sites) < min_sources or ("*", d, k) in rules:
            continue
        if any(is_descendant(d, e) for e in excludes):
            skipped.append((d, k, len(sites)))
            continue
        rules[("*", d, k)] = a
        promoted.append((d, k, len(sites)))
    return promoted, skipped


def hoist_subdomains(rules, minimum):
    groups = defaultdict(set)
    for (s, d, k), a in rules.items():
        if s == "*":
            continue
        r = registrable(s)
        if s != r:
            groups[(r, d, k, a)].add(s)
    hoisted = []
    for (r, d, k, a), subs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        if len(subs) >= minimum and (r, d, k) not in rules:
            rules[(r, d, k)] = a
            hoisted.append((r, d, k, len(subs)))
    return hoisted


# ------------------------------------------------------------------------ report
def heavy_sites(rules, n=10):
    counts = defaultdict(int)
    for (s, d, k) in rules:
        if s != "*":
            counts[s] += 1
    return sorted(counts.items(), key=lambda kv: -kv[1])[:n]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output", help="default: <input>.optimized.txt")
    ap.add_argument("--min-sources", type=int, default=5,
                    help="promote to global when used by this many distinct sites (0=off, default 5)")
    ap.add_argument("--hoist-subdomains", type=int, default=0,
                    help="collapse N+ sibling subdomain rules into the parent domain (0=off, default)")
    ap.add_argument("--exclude", action="append", default=[], metavar="DOMAIN",
                    help="never promote this destination (repeatable; subdomains included)")
    ap.add_argument("--exclude-file", help="file with one domain per line to never promote")
    ap.add_argument("--no-default-excludes", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="report only; write nothing")
    ap.add_argument("--report", help="write a full list of removed/added rules to this file")
    a = ap.parse_args()

    excludes = set(a.exclude)
    if a.exclude_file:
        excludes |= {l.strip() for l in Path(a.exclude_file).read_text().splitlines()
                     if l.strip() and not l.startswith("#")}
    if not a.no_default_excludes:
        excludes |= DEFAULT_EXCLUDES

    header, other, rules, dupes = parse(a.input)
    original = dict(rules)
    start = len(rules)
    log = []

    # Phase 1: safe pruning
    removed1 = prune(rules)
    after_phase1 = len(rules)

    # Phase 2: intentional consolidation, then prune again
    promoted, skipped, hoisted = [], [], []
    if a.min_sources > 0:
        promoted, skipped = promote_global(rules, a.min_sources, excludes)
    if a.hoist_subdomains > 0:
        hoisted = hoist_subdomains(rules, a.hoist_subdomains)
    removed2 = prune(rules) if (promoted or hoisted) else []

    final = len(rules)
    total_lines = len(header) + len(other) + final

    print(f"Input rules:                 {start + dupes}  ({dupes} exact duplicates)")
    print(f"Phase 1 (safe pruning):      -{len(removed1)} redundant  -> {after_phase1}")
    if a.min_sources > 0:
        print(f"Phase 2 global promotions:   +{len(promoted)} global rules "
              f"(threshold: {a.min_sources} sites)")
    if a.hoist_subdomains > 0:
        print(f"Phase 2 subdomain hoists:    +{len(hoisted)} parent-domain rules")
    if promoted or hoisted:
        print(f"Phase 2 cleanup:             -{len(removed2)} per-site rules now covered")
    print(f"Final rules:                 {final}  ({total_lines} lines incl. switches)")
    print(f"Reduction:                   {100 * (1 - final / max(start + dupes, 1)):.1f}%")
    input_lines = len(header) + len(other) + start + dupes
    print(f"Lines:                       {input_lines} -> {total_lines}  "
          f"({input_lines - total_lines} removed, net)\n")

    if promoted:
        print("Promoted to global (review these - they now apply on EVERY site):")
        for d, k, n in promoted:
            print(f"  * {d} {k} noop    (was on {n} sites)")
        print()
    if skipped:
        print("Would have been promoted but are in the exclude list (kept per-site):")
        for d, k, n in skipped:
            print(f"  {d} {k}    ({n} sites)")
        print()
    if hoisted:
        print("Hoisted to parent domain (now also applies to every subdomain of it):")
        for r, d, k, n in hoisted:
            print(f"  {r} {d} {k}    (replaced {n} subdomain rules)")
        print()
    heavy = heavy_sites(rules)
    if heavy:
        print("Sites with the most remaining per-site rules (candidates for manual review):")
        for s, n in heavy:
            print(f"  {n:3d}  {s}")

    if a.report:
        with open(a.report, "w", encoding="utf-8") as fh:
            fh.write("# REMOVED (phase 1: provably behaviour-preserving)\n")
            for (s, d, k), act, why in removed1:
                fh.write(f"{s} {d} {k} {act}    # {why}\n")
            fh.write("\n# ADDED (phase 2: broadens scope)\n")
            for d, k, n in promoted:
                fh.write(f"* {d} {k} noop    # global, was on {n} sites\n")
            for r, d, k, n in hoisted:
                fh.write(f"{r} {d} {k}    # hoisted from {n} subdomains\n")
            fh.write("\n# REMOVED (phase 2 cleanup)\n")
            for (s, d, k), act, why in removed2:
                fh.write(f"{s} {d} {k} {act}    # {why}\n")
        print(f"\nFull change list written to {a.report}")

    if not a.dry_run:
        out = a.output or str(Path(a.input).with_suffix("")) + ".optimized.txt"
        write(out, header, other, rules)
        print(f"\nWrote {out}")


if __name__ == "__main__":
    sys.exit(main())
