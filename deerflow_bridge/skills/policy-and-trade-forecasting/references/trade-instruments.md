# Trade instruments: authorities, implementation, measurement, retaliation

Load for US, China and EU trade instruments: clocks, implementation, effective-rate and flow measurement, retaliation and deals. Durations are statutory unless marked as priors; verify status in the primary record.

## 1. US tariff authorities

| Authority | Procedure | Clock | Scope and limits | Durability record (verify) |
|---|---|---|---|---|
| IEEPA (50 USC 1701–1707) | national emergency over an unusual and extraordinary foreign threat; an executive order modifies the tariff schedule | none; the emergency needs annual continuation | no stated rate cap; whether "regulate … importation" covers tariffs was the litigated question | the 2025 cases went CIT → Federal Circuit → Supreme Court: fetch the latest opinion, remand and refund orders; never assume the outcome |
| Section 232 (19 USC 1862) | Commerce (BIS) investigation, requested or self-initiated | report within 270 days; President decides within 90 and acts within 15 | product-scoped; derivatives added by inclusion processes | courts highly deferential; measures modified (quotas, TRQs, exemptions) more often than repealed |
| Section 301 (19 USC 2411) | USTR investigation of a country's practices: consultations, comments, hearing | determination generally within 12 months (18 for trade-agreement cases); modifiable under section 307 | country-scoped duties, fees, restrictions | lapses after four years unless domestic beneficiaries request continuation; the 2018–19 China lists outlasted a change of administration, rose on some lines after the four-year review and were upheld by the CIT (check the appeal) |
| Section 201 (19 USC 2251) | USITC injury finding on petition; President picks the remedy | ITC 120 days (150 if complex); President 60 | up to 4 years, extendable to 8, progressively liberalized | rare (2018 solar cells, washers) |
| Section 122 (19 USC 2132) | balance-of-payments grounds | at most 150 days unless an Act of Congress extends it | surcharge up to 15% ad valorem and/or quotas, nondiscriminatory in principle | bridge authority: compute expiry from the effective date |
| Section 338 (Tariff Act of 1930) | against countries that discriminate against US commerce | none | up to 50% additional | never used (verify): untested tail path |
| AD/CVD (Title VII, Tariff Act of 1930) | industry petition; Commerce sets margins, USITC finds injury | initiation about 20 days after petition; ITC preliminary 45 days; Commerce preliminary 65 days CVD (to 130) or 140 AD (to 190) after initiation, when cash deposits start; finals about 75 days later (to 135); ITC final; order | product × country; annual reviews; five-year sunset reviews | durable; sunset reviews often continue orders (USITC statistics); appeals to the CIT or USMCA panels |

**Authority substitution.** When an authority falls or expires, list each substitute with its clock and ceiling: Section 122 (fast, at most 15%, 150 days), Section 232 (product by product; existing actions widen through inclusions), Section 301 (country by country, after investigation and hearing), Section 338 (untested), statute (needs Congress), deal rates (set by executive order). A substitution scenario's earliest date is the fastest feasible substitute's start.

## 2. From announcement to collection

1. **Threat or announcement:** post, remarks, fact sheet. Not law.
2. **Signed order or proclamation** with annexes (HTS codes, rates, exemptions): Federal Register document number and citation.
3. **HTSUS change:** chapter 99 headings (9903.xx.xx) in the USITC HTS revision.
4. **CBP implementation:** CSMS messages fix the effective time (goods entered, or withdrawn from warehouse, for consumption on or after a date and time), in-transit rules, filing codes and stacking order.
5. **Payment:** at entry, or by periodic monthly statement on the 15th working day of the next month.
6. **Receipts:** Treasury MTS customs duties, cash, net of refunds.
7. **Liquidation** normally about a year after entry; protests within 180 days of liquidation; refunds; CIT residual-jurisdiction suits within two years.

**Before computing any rate** read: annexes and exclusions; USMCA-qualifying goods; deal rates; non-stacking rules; drawback; foreign-trade-zone status; de minimis; transshipment and undervaluation (CBP EAPA cases). **Pauses:** an order amending the effective date or rate; a suspension with expiry; an injunction (whom it covers); a vacatur stayed pending appeal, under which collection continues.

## 3. Effective tariff rate

- **Realized** ETR(t) = customs duties(t) ÷ customs-value imports for consumption(t), same coverage and months.
- **Statutory (pre-substitution)** = Σ τᵢ·wᵢ with base-period import weights; realized ≤ statutory through exemptions, import compression and evasion; realized ÷ statutory is collection efficiency.
- **Revenue decomposition** ΔD ≈ ETR·ΔM + M·ΔETR (+ ΔETR·ΔM) separates volume from rate.

| Use | Series | Notes |
|---|---|---|
| Monthly cash duties | usgov:treasury/mts_customs_duties | USD, NSA, net of refunds (can be negative), a month behind entries; fiscal year October–September; compare the year-ago month or year-to-date |
| Quarterly accrual duties | fred:B235RC1Q027SBEA | billions USD at an annual rate (divide by 4 for a quarter) |
| Share of receipts | usgov:treasury/mts_receipts | seasonal (April and September receipts) |
| Imports from China | fred:IMPCH | millions USD, customs basis, NSA |
| Exports to China | fred:EXPCH | F.A.S. basis, NSA |
| Trade balance; real imports | fred:BOPGSTB; fred:IMPGSC1 | never an ETR denominator |
| Import and export prices | bls:EIUIR; bls:EIUIQ | import prices exclude duties |
| Currency offset | fred:DEXCHUS; fred:DTWEXBGS | yuan per USD; broad dollar |
| World trade volume | imf:WEO/G001.TRADEPCH.A | current and future years are projections (REPORTED) |

Denominator: data_search "US imports for consumption customs basis", or Census FT-900 or USA Trade Online. Country or product rates: USITC DataWeb "calculated duties" and "customs value" by HTS line and country.

**Steps:** (1) use three-month or fiscal-year sums; (2) pair MTS month t+1 with imports in month t, or use accrual data; (3) tag the ratio REPORTED; (4) treat S2 figures (Yale Budget Lab, Penn Wharton Budget Model, Tax Foundation, PIIE, CBO) as estimates and note their statutory or realized basis.

**Anchors settle on one stored observation** (a named month, quarter or year, optionally #yoy or #pct), never on a sum, average or own ratio; thresholds come from evidence. Templates: fred:B235RC1Q027SBEA in YYYY-Qn, billions USD at an annual rate (annual revenue, no monthly seasonality); usgov:treasury/mts_customs_duties in a named month, USD (seasonal, net of refunds: set the threshold against the year-ago month); fred:IMPCH#yoy or bls:EIUIR#yoy in a named month, percent.

**Traps:** refunds after a ruling depress cash receipts while replacement duties ramp, so a drop is not a lower legal rate; front-loading inflates imports before an effective date, then reverses; one annualized month ignores seasonality and refunds.

## 4. Flows, diversion and pass-through

- **Rerouting vs transshipment vs relocation:** rerouting shows a third country's US exports rising with its imports of Chinese inputs (GACC exports by destination); transshipment shows abrupt US imports in HTS lines it never produced, plus CBP EAPA findings; relocation shows plant investment there, years later.
- **Mirror gap:** China's reported exports to the US (GACC, FOB) minus US imports from China (Census) reflects valuation, Hong Kong re-exports, timing, de minimis and misdeclaration. Track the change, not the level.
- **Front-loading and payback:** a surge before effective dates, then a dip; check inventories (data_search "US wholesale inventories") and foreign-trade-zone admissions.
- **Pass-through:** bls:EIUIR is measured before duties. Falling import prices with steady volumes mean exporters absorb; flat import prices with rising domestic goods prices (data_search "CPI commodities less food and energy commodities") mean US buyers pay. Prior to verify: studies of the 2018–19 tariffs found near-complete pass-through into duty-inclusive US import prices (NBER and journal studies). Yuan depreciation offsets part of a China tariff.

## 5. Retaliation and deal patterns (priors to verify with dated records)

- **China:** counter-tariffs by State Council Tariff Commission announcement, usually within days, matched in rate or aimed at salient US exports (farm goods, energy); non-tariff levers: MOFCOM export controls on critical minerals and technology, Unreliable Entity List and control-list additions, trade-remedy and antitrust (SAMR) probes, GACC import suspensions; exclusion processes for US goods. De-escalation usually means time-limited suspensions: record each expiry date.
- **EU:** rebalancing under the Enforcement Regulation; countermeasure lists are consulted publicly and adopted with deferred or suspended application during talks; the Anti-Coercion Instrument is the deterrent.
- **Canada and Mexico:** Canadian surtaxes by Canada Gazette order, with remission; Mexican decrees in the DOF; USMCA review and disputes.
- **Deals:** framework or joint statement → legal text, if any → US implementing order and HTSUS change → partner's implementing acts → verification in trade data. Purchase pledges are weak evidence: China's Phase One (2020) pledges were missed by a wide margin (PIIE tracking).
- **WTO:** disputes take years and panel reports can be appealed into the void (no Appellate Body since December 2019); rulings rarely bite within a forecast window.

## 6. China instruments

| Instrument | Legal basis | Record | Pattern |
|---|---|---|---|
| Item export controls (两用物项) | Export Control Law (2020); Dual-Use Items Export Control Regulations (2024) | numbered MOFCOM 公告 (often with GACC) listing HS codes and effective dates | licence required, review clock set by regulation (verify); effective at once or within weeks; suspensions by a new dated 公告 |
| Export-control control list (出口管制管控名单) | Export Control Law | MOFCOM announcements | entity-specific export bans |
| Unreliable Entity List (不可靠实体清单) | 2020 Provisions | working-mechanism announcements | trade and investment bans, fines, entry limits |
| Countermeasures (反制措施) | Anti-Foreign Sanctions Law (2021) | MFA decisions | asset freezes, bans on dealings |
| Additional tariffs (加征关税), exclusions (排除) | Customs Tariff Law countermeasure clause | State Council Tariff Commission announcements | usually effective within about a week |
| Trade remedies (反倾销, 反补贴, 保障措施) | AD and CVD Regulations | MOFCOM Trade Remedy and Investigation Bureau | normally within 12 months, extendable by 6; preliminary deposits; price undertakings as negotiated exit |
| Technology export catalogue (禁止出口限制出口技术目录) | Foreign Trade Law | MOFCOM and MOST revisions | licences for listed technology |
| Laws | Legislation Law | NPCSC sessions about every two months; usually three readings; comment on 中国人大网 after the first | passage near-certain once put to a vote; uncertainty is timing and text (NPCSC annual legislative plan) |

Data and statements: GACC monthly trade by country and HS code (January and February combined), MOFCOM's regular press conference, the State Council gazette. Chinese queries: 商务部公告 出口管制; 两用物项 出口许可; 国务院关税税则委员会 公告; 不可靠实体清单工作机制; 反倾销 初裁 终裁; 海关总署 进出口 国别.

## 7. EU instruments

- **Competence:** trade is exclusive EU competence (Article 207 TFEU). The Commission proposes and negotiates; the Council adopts most trade acts by qualified majority; agreements need Council signature and Parliament consent, and mixed agreements national ratification too.
- **Ordinary legislative procedure:** Commission proposal (COM number, procedure 20YY/NNNN(COD)) → Parliament committee report and plenary position → Council general approach → trilogues → provisional agreement → formal adoption by both → Official Journal → entry into force (often 20 days later) → application dates. Directives then need transposition by the act's deadline, enforced by letter of formal notice → reasoned opinion → Court of Justice. Prior: most files close at first reading after trilogues, typically 1.5–2 years after the proposal (Parliament activity reports; OEIL); some proposals are withdrawn in Commission work programmes.
- **Trade defence** (Regulations 2016/1036 and 2016/1037): anti-dumping provisional duties normally within 7 months and no later than 8 after initiation, definitive within 14 months; anti-subsidy definitive within 13; the member-state committee blocks only by qualified majority against; expiry reviews at five years. Records: DG TRADE case pages, Official Journal implementing regulations.
- **Anti-Coercion Instrument** (Regulation 2023/2675): Commission examination → Council determination by qualified majority → engagement → response measures by implementing act. Check whether it has been activated.
- **Others:** Foreign Subsidies Regulation, International Procurement Instrument, CBAM phase-in, Enforcement Regulation 654/2014. CFSP sanctions need unanimity, and Russia's economic sanctions are renewed every six months: each renewal is a veto point.

## 8. US export controls and sanctions

- **BIS (EAR):** Entity List additions and licensing policies arrive as Federal Register rules, often effective on public display; foreign direct product rules extend reach; licence decisions are unpublished, so disclosures about them are REPORTED.
- **OFAC:** designations on its Recent Actions page; general licences carry expiry dates (signposts); delisting is rare and slow.
- **Statutory sanctions** (CAATSA for Russia, Iran sanctions statutes) need congressional review or waivers on fixed cycles before relief; executive-order sanctions can be lifted by the President. Weight relief scenarios accordingly; sanctions as conflict coercion → geopolitical-forecasting.
