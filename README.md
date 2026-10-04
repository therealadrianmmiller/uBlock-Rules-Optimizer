# uBlock-Rules-Optimizer

Optmizes uBlock Rules - Shrink a uBlock Origin "My rules" (dynamic filtering) export

## What It DOESNT Do:

It doesnt improve speed/efficiency for ruleset when used by uBlock Origin - due to the way uBlock does lookups

## What It Does:

It helps (me at least) optimise the rules for maintenance/readibilty

## How It Does It: 

- PRUNE (behaviour-preserving, always on)
  Removes a rule only if a simulation of uBO's rule resolution proves that every request resolves exactly as before. Catches exact duplicates, per-site rules
  already covered by a global/parent-domain rule, and rules covered by a parent destination (e.g. `* cdnjs.cloudflare.com` when `* cloudflare.com` exists).

  Example: 

```
auth.13cabs.com.au auth0.com * noop
auth.13cabs.com.au cdn.auth0.com * noop
book.13cabs.com.au auth0.com * noop
welcome.auspost.com.au auth0.com * noop
auth.colesgroupprofile.com.au auth0.com * noop
login.discogs.com auth0.com * noop
auth.kmart.com.au auth0.com * noop
login.service.nsw.gov.au auth0.com * noop
auth.onepass.com.au auth0.com * noop
auth.petbarn.com.au auth0.com * noop
id.realestate.com.au auth0.com * noop
auth.woolworths.com.au auth0.com * noop
auth.zip.co auth0.com * noop`
```
becomes (stripping the lines above):

```
* auth0.com * noop
```

For my own personal rules file, it removed 400 lines


- PROMOTE / HOIST (intentionally loosens scope - you control it)

     --min-sources N        Promote `site dest type noop` to `* dest type noop` when N or more
                            distinct sites (registrable domains) use it. Default 5. 0 disables.

     --hoist-subdomains M   If M+ subdomains of one site share a rule (a.x.com, b.x.com, ...),
                            replace them with a single rule on x.com. Default 0 (off).

     After either, PRUNE runs again to delete the now-redundant per-site rules.

## Usage:

ublock_rules_optimizer.py / ublock_rules_optimizer.exe (single file compiled for Windows) is executed command prompt/terminal - this is not a GUI app

Basic usage (same as using Advanced Option `ublock_rules_optimizer.py my-rules.txt --min-sources 5`):

`ublock_rules_optimizer.py my-rules.txt # writes my-rules.optimized.txt`

Advanced Options:

```
ublock_rules_optimizer.py my-rules.txt --dry-run (report only)
ublock_rules_optimizer.py my-rules.txt --min-sources <number of matches needed to promote> (default = 5)
ublock_rules_optimizer.py my-rules.txt --hoist-subdomains <number of matches needed to hoist> (default = 0 (Off))
ublock_rules_optimizer.py my-rules.txt --exclude <domain name>
ublock_rules_optimizer.py my-rules.txt --exclude-file <filename including exclusions, one domain per line>
ublock_rules_optimizer.py my-rules.txt --no-default-excludes (disable inbuilt exclusions)
ublock_rules_optimizer.py my-rules.txt --report <report filename>
```

Note: The script includes exclusions for a range of domains to not promote them as they are known for ads/tracking across domains

The included exclusions are: 

```
"google.com", "facebook.com", "facebook.net", "fbcdn.net", "twitter.com", "x.com", "doubleclick.net", "google-analytics.com", "googlesyndication.com", "googleadservices.com", "adnxs.com", "criteo.com", "taboola.com", "outbrain.com","hotjar.com", "amazon.com", "microsoft.com", "linkedin.com", "tiktok.com",
```


Import the result via uBlock Origin > Dashboard > My rules > Import from file, then Commit.

Keep a copy of the original export; the script never modifies its input.

## Download:

See Releases for zip containing both .py amd .exe
