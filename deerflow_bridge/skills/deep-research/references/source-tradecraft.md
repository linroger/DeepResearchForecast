# Source and Verification Tradecraft

Load this reference when designing queries, collecting evidence, resolving a difficult KIQ, or grading sources. It does not impose a prose length requirement.

## Research design

For each KIQ record its claim type—fact, statistic, mechanism, intention, estimate, projection, or contested interpretation—and name the best likely source class before searching. State the prior and the observation most likely to change it.

## Search craft

- Target the document: filing, annual/quarterly report, transcript, statistical release, regulation, bill, docket, judgment, tender, patent, trial registry, standard, dataset, or minutes.
- Use exact phrases for distinctive language; `site:` for authoritative domains; `filetype:pdf` for reports; date terms for time-bounded facts; exclusions for dominant noise.
- Pivot by actor, organization, cited author, document type, jurisdiction, local language, professional vocabulary, or time window.
- Mine a strong page's citations before launching another blind search.
- For changed/deleted pages, use an official archive or the Wayback Machine. Never guess paywalled content.

## Source map

| Domain | Preferred primary origins |
|---|---|
| Macro/economy | national statistics agencies, central banks, IMF, World Bank, BIS, OECD; retrieve their series with `data_search` → `data_get` when available |
| Companies/finance | exchange disclosures, SEC/local filings, earnings transcripts, audited reports |
| Technology | company roadmap/capex disclosures, standards bodies, official export-control texts, reputable industry datasets |
| Policy/regulation | enacted/proposed text, regulator notices, Federal Register, committee testimony, court dockets |
| Science/medicine | peer-reviewed articles, trial registries, regulator assessments, systematic reviews |
| Geopolitics/conflict | official statements from each side, multilateral bodies, event datasets, evidence-showing OSINT |
| Public opinion | named pollsters with methodology, field dates, sample, and question wording |

Primary does not mean unbiased: it is authoritative about what the actor reported or stated, not the truth of its persuasion.

## Pre-fetch screen

Check author/institution, date, original versus rewrite, specificity, method/data disclosure, incentives, domain reputation, and headline/content match. Two or more red flags usually mean S4: skip.

## Evidence ledger and grading

Example shape:

```text
[KIQ-2] Claim: TSMC 2026 capex guidance = $52–56B
  S1: Q4 earnings call, 2026-01-16, URL...
  S2: Reuters, same date, cites the call (not independent)
  grade: B1; status: single origin; gap: geographic split
```

Admiralty shorthand: A/S1 reliable, B/S2 usually reliable, C/S3 conditional, D/suspect; credibility 1 confirmed independently, 2 probable/partly corroborated, 3 possible, 4 doubtful. A load-bearing claim should reach B2 or better, otherwise upgrade, label, or drop it.

## Verification

- Lateral-read unknown sources and authors.
- Trace striking repeated statistics or wording to the earliest underlying origin.
- Verify load-bearing quotes against transcripts/video when possible.
- Distinguish publication date from data as-of date.
- Reconcile definitions before averaging conflicting numbers.
- Check million/billion, percentages versus percentage points, currency, real/nominal, totals, denominators, and CAGR-implied endpoints.
- Treat estimates/projections as method + assumptions + range, intentions as words + feasibility, rumors as rumors.
- For a series `data_get` stored, quote the stored value, unit and period with its `[S<n>]`; keep each observation's status (observed, preliminary, estimate, projection) and never present a publisher projection as observed history. Use web pages for the release narrative, not to retype the numbers.

## Adversarial analysis

- ACH-lite: list plausible hypotheses and ask which evidence discriminates among them.
- Key assumptions: evidence, fragility, impact if false.
- Disconfirmation: search the strongest opposing case and credible criticism.
- Premortem: imagine the forecast failed and identify why; turn answers into risks/indicators.
- Consensus check: determine whether apparent agreement shares one origin or incentive.

## Obstacles

- Paywall: find the underlying primary document, wire coverage, author copy, or archive; label headline-only evidence weak.
- Dead page: archive or locate the original document.
- Thin English results: local-language S1/S2 pivot and verify translation.
- Only S3/S4: drop or explicitly label single weak source.
- Tool failure/empty page: one changed-approach retry, then route around and record the gap.
- Conflicting numbers: show the range, definitions/windows/methods/incentives, and weighting rationale.
