# Macro base rates — counting rules on stored history, priors to verify

Load for base-rate KIQs. Counts you compute are REPORTED. The documented priors below are leads to verify by fetching the named source class: never cite this file.

## 1. What storage allows

- **240-observation cap**: data_get keeps the newest 240 observations — about 20 years of a monthly series, 60 of a quarterly one, all of an annual one. Daily series become monthly (≈20 years).
- **The first call fixes the window** for the whole run, so pass `start` on that first call (30 years back is the engine default for base-rate KIQs). For quarterly GDP an earlier start such as 1967 still fits within 240 quarters; a series already stored (e.g. prefetched) keeps its window.
- **The forecast stage reuses it**: it computes an empirical outside view from the stored window — the share of historical h-step changes that would cross the threshold, needing ≥30 samples, plus the σ distance. A short or regime-specific window biases that number: prefer the longer history and say which years it covers.
- **Long-history choices**:
  - **Growth, recession**: fred:A191RL1Q225SBEA and fred:GDPC1 (quarterly, from 1947); wb:IMF_WEO_NGDP_RPCH/USA (annual from 1980, projections included: count observed years only); wb:WB_WDI_NY_GDP_MKTP_KD_ZG/CHN.
  - **Inflation**: bis:WS_LONG_CPI/M.US.771 and bis:WS_LONG_CPI/M.CN.771 (monthly YoY, 20 years kept); wb:IMF_WEO_PCPIPCH/USA and wb:WB_WDI_FP_CPI_TOTL_ZG/CHN (annual).
  - **Policy rates**: fred:FEDFUNDS and bis:WS_CBPOL/M.US (monthly, 20 years kept). fred:DFEDTARU exists only since the target range began (December 2008): older Fed cycles need the Fed's historical target-change tables (S1, web).
  - **Labour**: fred:UNRATE, fred:SAHMREALTIME (monthly); wb:IMF_WEO_LUR/USA (annual).
  - **Fiscal**: fred:FYFSGDA188S (annual), fred:GFDEGDQ188S (quarterly).
  - **Curve, credit**: fred:T10Y3M (20 years as months); fred:BAMLH0A0HYM2 holds only about 3 years on FRED (ICE licensing), so long spread counts need an S1 or S2 history; bis:WS_CREDIT_GAP/Q.US.P.A.C (quarterly).
- **Beyond the stored window**, use documented chronologies fetched as S1 (NBER business-cycle dates, Fed target histories, BLS and BEA historical tables), and say that the count mixes sources.

## 2. The counting rule (write it before you count)

1. **Trigger** — the observable state that opens an episode (e.g. "Sahm indicator ≥ 0.50", "first cut after ≥ 6 months without one", "12-month core inflation peaks above 4%").
2. **Window** — how long after the trigger the outcome may occur; match the question horizon.
3. **Outcome** — the resolving event, defined on the question's own series where possible.
4. **Independence** — one episode per cycle; overlapping windows and re-triggers inside a window count once.
5. **Denominator** — every trigger, including false alarms; report censored (still-open) episodes separately.
6. **Result** — "k of n episodes (series, years covered, rule) — REPORTED". With n < 20, also give (k+1)/(n+2); with n < 10, give a range and shrink toward the unconditional rate.
7. **Analogy check** — name what differs now (starting level, shock type, policy framework, fiscal stance). Never drop an episode for "looking different" without a stated rule.

## 3. Worked rules (method first; every number to be counted or verified)

### 3.1 Recession frequency (unconditional)
- **Rule**: NBER peaks per year of history.
- **Prior to verify** (NBER chronology, S1): 12 recessions began between 1948 and 2020, about one year in six or seven. Four began after 1983 (1990, 2001, 2007, 2020), about one year in eleven. Choose the class (post-war vs post-1983) and justify the choice.
- **Horizon**: P(at least one start within h years) ≈ 1 − (1 − p)^h, before conditioning. Illustration only: p = 0.09 and h = 1.25 give 1 − 0.91^1.25 ≈ 0.11.
- **Resolution traps**:
  - NBER dates peaks months after the fact (historically about 4 to 12 months for peaks, longer for troughs). An "NBER-declared by date" question can fail even after a recession has begun.
  - "Two negative quarters" is a different event: count it on fred:A191RL1Q225SBEA (negative SAAR q/q twice running). It has diverged from NBER dating — early estimates for the first half of 2022 are the known case; check the current vintage.

### 3.2 Recession signals (conditional)
- **Sahm rule**:
  - Trigger: fred:SAHMREALTIME ≥ 0.50 (catalog note). Outcome: an NBER peak from 12 months before to 6 months after the trigger.
  - Prior to verify (Sahm 2019; FRED and Fed notes): it flagged every recession since 1970 near its start, with very few false alarms before its 2024 trigger. Keep 2024 in the denominator with its current outcome.
- **Yield curve**:
  - Trigger: the first month of a run of ≥ 3 negative monthly averages of fred:T10Y3M. Outcome: an NBER peak within 24 months.
  - Prior to verify (NY Fed yield-curve research; Estrella–Mishkin): inversions preceded each recession since the late 1960s, with leads of roughly 6–24 months. The long 2022–24 inversion is the key recent test: count it with its current outcome.
  - The stored 20 years cover only part of this record; fetch the NY Fed page for the rest.
- **Unemployment momentum**: prior to verify — once unemployment rose about half a point above its 12-month low, it has historically kept rising toward recession levels. That is the logic behind the Sahm rule, and 2024 is again the test case.
- **Claims**: trigger "4-week average of fred:ICSA up ≥ X% from its cycle low". Fix X before counting and report the false alarms.
- **Consensus as evidence**: prior to verify (An, Jalles & Loungani, IMF Working Paper 2018) — private-sector consensus a year ahead anticipated only a handful of roughly 150 recessions across 63 economies in 1992–2014. A consensus of "no recession" is weak evidence.

### 3.3 Fed easing cycles
- **Rule**: a cycle starts with the first cut after ≥ 6 months without one (or after a hike) and ends with the last cut before ≥ 6 months without one (or before a hike). Outcomes: number of cuts, total bp, duration, and whether an NBER recession overlapped.
- **Data**: fred:FEDFUNDS and bis:WS_CBPOL/M.US (20 years stored); older cycles from the Fed's historical target changes (S1).
- **Documented priors to verify**:
  - "Insurance" cycles without recession (1995–96, 1998, 2019) totalled about 75 bp each.
  - Recession-linked cycles (2001–03, 2007–08, 2020) cut roughly 150–550 bp and ended at or near the lower bound.
  - The class split is the scenario split: P(deep cycle) ≈ P(recession over the horizon). A cycle that fits neither class (for example, cuts that only unwind a restrictive stance) gets its own row: classify each cycle by the motive the FOMC statements give, not by its size.
- **Pause length**: count the months between the last hike and the first cut on the stored series; report the range, not a mean of a few cases.

### 3.4 Disinflation and inflation thresholds
- **Rule for "below X by T"**: take episodes where the same 12-month measure stood within ±0.3 pp of today's level with the same recent direction, and count how often it was below X h months later (h = months to T). Compare with the forecast stage's mechanical h-step outside view, and explain any gap.
- **Conditioning to state**: headline–core gap (energy), services-ex-shelter momentum (bls:CUSR0000SASLE), wages (bls:CIU1010000000000A), expectations (fred:MICH, fred:T5YIFR).
- **Qualitative priors to verify** (Fed and BIS research): the last stretch toward target is usually slower than the first decline; headline crosses thresholds faster than core in energy-driven episodes.
- **Annual long history**: wb:IMF_WEO_PCPIPCH/USA (annual average) for counts of years above or below a threshold; exclude projection years.

### 3.5 Soft-landing frequency
- **The count depends on the definition**: a strict one (no recession within two years of the last hike, unemployment up < 1 pp) versus looser "softish" ones.
- **Prior to verify**: Blinder (2023, Journal of Economic Perspectives) classifies the Fed's tightening cycles since 1965. Strict definitions leave few soft landings, with 1994–95 the canonical case. State the definition, then count.

### 3.6 Decisions versus market pricing
- **Prior to verify** (event-study literature, e.g. Kuttner 2001; Gürkaynak, Sack & Swanson 2005): since the Fed began announcing decisions in 1994, large surprises relative to eve-of-meeting futures have been rare. Near-dated pricing is a strong prior for the next meeting; pricing 6–12 months out carries large errors.
- **Rule**: weight market odds heavily for the next meeting and less for later ones. Widen with the SEP's historical-error table (S1).
- **BOJ**: it has surprised more often (2016 negative rates, 2022 band change). Verify per bank.

### 3.7 Projection-error base rates
- **SEP**: each release's table of historical forecast errors (S1) gives typical 1–3-year misses for the policy rate, unemployment, inflation and GDP.
- **IMF WEO**: compare vintages for the same target year — the catalog's dated WEO vintage series (imf:WEO_2025_OCT_VINTAGE/CHN.NGDP_RPCH.A, imf:WEO_2026_APR_VINTAGE/CHN.NGDP_RPCH.A) against the latest (wb:IMF_WEO_NGDP_RPCH/CHN). The revision direction is information; turning points are rarely projected (IMF IEO evaluations).
- **CBO**: CBO's own evaluations of its baseline projections (S1) give typical deficit-projection errors; policy changes after the baseline are a main source.

### 3.8 China
- **Reported growth versus the NPC target**: count the years in which NBS growth was ≥ target − 0.1 pp, using the Government Work Reports.
  - Prior to verify: met or nearly met in most years since the 1990s, with clear misses in shock years (e.g. 2022); no target was set in 2020.
  - This is a reporting base rate: cross-check it against nominal GDP, the deflator and activity proxies.
- **Deflation spells**: count months and runs of negative CPI YoY (bis:WS_LONG_CPI/M.CN.771) and PPI YoY (NBS, web).
- **Easing after a stance shift**: how often an announced shift (e.g. to 适度宽松) was followed by an LPR or RRR move within N months, from the PBoC announcement history (S1, web).

## 4. From base rates to plan-time scenario weights

1. **Start** from the unconditional regime frequency for the horizon (3.1, 3.5).
2. **Condition** on hard signals by their counted track record (3.2): move toward the conditional rate in proportion to the hit rate, not to the narrative.
3. **Market check**: futures paths and prediction markets. If they disagree widely, keep the base-rate anchor and record the gap for the forecast stage.
4. **Weights**: integers summing to 100, MECE; merge a scenario under 5 unless it is a signposted tail. Name each scenario by its signature on an anchor series, so binaries and scenario metric ranges can map onto it.
