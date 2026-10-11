# Official data series catalog

Generated from `deerflow_bridge/data_catalog.py` by `render_catalog_markdown()`; do not edit by hand (regenerate with `python deerflow_bridge/data_catalog.py --write-markdown`).

277 curated series across 6 providers. Every id was verified live on 2026-10-11: the provider returned recent data, and titles and units come from its own metadata. Pass an id exactly as written to `data_get`; `data_search` searches this catalog first.

Columns: Freq D/W/M/Q/A = daily/weekly/monthly/quarterly/annual; SA = seasonally adjusted, SAAR = seasonally adjusted annual rate, NSA = not seasonally adjusted, blank = not applicable or not published; Geo = ISO3 code, EMU = euro area, WLD = world or global benchmark.

## Providers

| Provider | Source | Use for | Example id | Series |
|---|---|---|---|---|
| fred | FRED (Federal Reserve Bank of St. Louis) | US macro, labor, prices, policy rates and the Treasury curve, credit spreads, dollar FX, energy prices, money; free-text search over about 800,000 series | `fred:UNRATE` | 70 |
| bls | U.S. Bureau of Labor Statistics | authoritative US CPI/PPI detail, average prices, payrolls, JOLTS, wages, ECI, productivity, state unemployment; no free-text search, use the catalog | `bls:CUUR0000SA0` | 45 |
| bis | Bank for International Settlements (BIS) | cross-country central bank policy rates, credit-to-GDP gaps, total credit, debt service ratios, property prices, USD and effective exchange rates, central bank assets | `bis:WS_CBPOL/M.US` | 50 |
| imf | International Monetary Fund (IMF) | primary commodity prices (oil, gas, metals incl. lithium and cobalt, food), CPI inflation by country, WEO world and euro-area aggregates and past WEO vintages; slow (30-50 s per call), best prefetched | `imf:PCPS/G001.POILBRE.USD.M` | 40 |
| wb | World Bank Data360 | annual cross-country history (World Development Indicators) and official projections: IMF WEO by country to 2031, World Bank Global Economic Prospects | `wb:IMF_WEO_NGDP_RPCH/CHN` | 54 |
| usgov | U.S. Government Open Data (Treasury Fiscal Data, USAspending) | federal debt to the penny, monthly receipts, outlays and deficit, average interest rate on Treasury debt, Treasury reporting exchange rates, federal award spending, SEC company facts | `usgov:treasury/mts_deficit` | 18 |

## fred — FRED (Federal Reserve Bank of St. Louis)

| Series id | Title | 中文 | Units | Freq | SA | Geo | Notes |
|---|---|---|---|---|---|---|---|
| `fred:A191RL1Q225SBEA` | Real Gross Domestic Product | 美国实际GDP增长率（环比折年率） | Percent Change from Preceding Period | Q | SAAR | USA | Quarter-on-quarter change at a seasonally adjusted annual rate, not year-over-year; advance estimates are revised twice. |
| `fred:GDPC1` | Real Gross Domestic Product | 美国实际国内生产总值 | Billions of Chained 2017 Dollars | Q | SAAR | USA | Level in chained 2017 dollars; use transform yoy for year-over-year growth. |
| `fred:GDP` | Gross Domestic Product | 美国名义国内生产总值 | Billions of Dollars | Q | SAAR | USA | Current dollars; use GDPC1 for real output. |
| `fred:INDPRO` | Industrial Production: Total Index | 美国工业生产指数 | Index 2017=100 | M | SA | USA |  |
| `fred:TCU` | Capacity Utilization: Total Index | 美国产能利用率 | Percent | M | SA | USA |  |
| `fred:RSAFS` | Advance Retail Sales: Retail Trade and Food Services | 美国零售和餐饮销售额 | Millions of Dollars | M | SA | USA | Advance estimate in nominal dollars; revised in the following two months. |
| `fred:RRSFS` | Advance Real Retail and Food Services Sales | 美国实际零售和餐饮销售额 | Millions of 1982-84 CPI Adjusted Dollars | M | SA | USA |  |
| `fred:PCEC96` | Real Personal Consumption Expenditures | 美国实际个人消费支出 | Billions of Chained 2017 Dollars | M | SAAR | USA |  |
| `fred:DSPIC96` | Real Disposable Personal Income | 美国实际个人可支配收入 | Billions of Chained 2017 Dollars | M | SAAR | USA |  |
| `fred:PSAVERT` | Personal Saving Rate | 美国个人储蓄率 | Percent | M | SAAR | USA |  |
| `fred:TOTALSA` | Total Vehicle Sales | 美国汽车总销量 | Millions of Units | M | SAAR | USA |  |
| `fred:HOUST` | New Privately-Owned Housing Units Started: Total Units | 美国新屋开工 | Thousands of Units | M | SAAR | USA |  |
| `fred:PERMIT` | New Privately-Owned Housing Units Authorized in Permit-Issuing Places: Total Units | 美国新屋营建许可 | Thousands of Units | M | SAAR | USA |  |
| `fred:CSUSHPISA` | S&P Cotality Case-Shiller U.S. National Home Price Index | 标普凯斯-席勒美国全国房价指数 | Index Jan 2000=100 | M | SA | USA | Published with a two-month lag (three-month moving average). |
| `fred:MSPUS` | Median Sales Price of New Houses Sold for the United States | 美国新房销售价格中位数 | Dollars | Q | NSA | USA |  |
| `fred:UMCSENT` | University of Michigan: Consumer Sentiment | 密歇根大学消费者信心指数 | Index 1966:Q1=100 | M | NSA | USA |  |
| `fred:MICH` | University of Michigan: Inflation Expectation | 密歇根大学一年期通胀预期 | Percent | M | NSA | USA | Median expected price change over the next 12 months. |
| `fred:M2SL` | M2 | 美国M2货币供应量 | Billions of Dollars | M | SA | USA |  |
| `fred:WALCL` | Assets: Total Assets: Total Assets (Less Eliminations from Consolidation): Wednesday Level | 美联储资产负债表总资产 | Millions of U.S. Dollars | W | NSA | USA |  |
| `fred:RECPROUSM156N` | Smoothed U.S. Recession Probabilities | 美国衰退概率（平滑） | Percent | M | NSA | USA | Model estimate published with a lag of about two months. |
| `fred:NFCI` | Chicago Fed National Financial Conditions Index | 芝加哥联储全国金融状况指数 | Index | W | NSA | USA | Zero is average; positive values mean tighter than average conditions. |
| `fred:CPIAUCSL` | Consumer Price Index for All Urban Consumers: All Items in U.S. City Average | 美国消费者价格指数（CPI-U，全部项目） | Index 1982-1984=100 | M | SA | USA | Index level: use transform yoy for the inflation rate. Headline YoY as published uses the NSA series bls:CUUR0000SA0. October 2025 is missing (2025 federal shutdown). |
| `fred:CPILFESL` | Consumer Price Index for All Urban Consumers: All Items Less Food and Energy in U.S. City Average | 美国核心CPI（剔除食品和能源） | Index 1982-1984=100 | M | SA | USA | Index level: use transform yoy for the core inflation rate. |
| `fred:PCEPI` | Personal Consumption Expenditures: Chain-type Price Index | 美国个人消费支出价格指数 | Index 2017=100 | M | SA | USA | Index level: use transform yoy for PCE inflation. |
| `fred:PCEPILFE` | Personal Consumption Expenditures Excluding Food and Energy (Chain-Type Price Index) | 美国核心PCE价格指数 | Index 2017=100 | M | SA | USA | The Federal Reserve's 2 percent target is defined on PCE inflation; use transform yoy. |
| `fred:UNRATE` | Unemployment Rate | 美国失业率 | Percent | M | SA | USA | October 2025 is missing (2025 federal shutdown); BLS source series bls:LNS14000000. |
| `fred:U6RATE` | Total Unemployed, Plus All Persons Marginally Attached to the Labor Force, Plus Total Employed Part Time for Economic Reasons, as a Percent… | 美国U-6广义失业率 | Percent | M | SA | USA |  |
| `fred:PAYEMS` | All Employees, Total Nonfarm | 美国非农就业人数 | Thousands of Persons | M | SA | USA | Level in thousands; monthly job gains are the first difference. Benchmark revisions each February. |
| `fred:ICSA` | Initial Claims | 美国首次申请失业救济人数 | Number | W | SA | USA |  |
| `fred:CCSA` | Continued Claims (Insured Unemployment) | 美国持续申请失业救济人数 | Number | W | SA | USA |  |
| `fred:CIVPART` | Labor Force Participation Rate | 美国劳动参与率 | Percent | M | SA | USA |  |
| `fred:JTSJOL` | Job Openings: Total Nonfarm | 美国职位空缺数（JOLTS） | Level in Thousands | M | SA | USA |  |
| `fred:CES0500000003` | Average Hourly Earnings of All Employees, Total Private | 美国私营部门平均时薪 | Dollars per Hour | M | SA | USA |  |
| `fred:SAHMREALTIME` | Real-time Sahm Rule Recession Indicator | 萨姆规则衰退指标（实时） | Percentage Points | M | SA | USA | Signals a recession when the value reaches 0.50 percentage points. |
| `fred:FEDFUNDS` | Federal Funds Effective Rate | 联邦基金有效利率（月均） | Percent | M | NSA | USA | Monthly average of the daily effective rate; the FOMC target range upper limit is fred:DFEDTARU. |
| `fred:DFF` | Federal Funds Effective Rate | 联邦基金有效利率（日度） | Percent | D | NSA | USA | Seven-day daily series (weekends carry the prior business day). |
| `fred:DFEDTARU` | Federal Funds Target Range - Upper Limit | 联邦基金目标利率区间上限 | Percent | D | NSA | USA | Step series that changes only at FOMC decisions; the lower limit is 25 basis points below. |
| `fred:SOFR` | Secured Overnight Financing Rate | 有担保隔夜融资利率 | Percent | D | NSA | USA |  |
| `fred:DGS3MO` | Market Yield on U.S. Treasury Securities at 3-Month Constant Maturity, Quoted on an Investment Basis | 美国3个月期国债收益率 | Percent | D | NSA | USA |  |
| `fred:DGS2` | Market Yield on U.S. Treasury Securities at 2-Year Constant Maturity, Quoted on an Investment Basis | 美国2年期国债收益率 | Percent | D | NSA | USA |  |
| `fred:DGS10` | Market Yield on U.S. Treasury Securities at 10-Year Constant Maturity, Quoted on an Investment Basis | 美国10年期国债收益率 | Percent | D | NSA | USA |  |
| `fred:DGS30` | Market Yield on U.S. Treasury Securities at 30-Year Constant Maturity, Quoted on an Investment Basis | 美国30年期国债收益率 | Percent | D | NSA | USA |  |
| `fred:T10Y2Y` | 10-Year Treasury Constant Maturity Minus 2-Year Treasury Constant Maturity | 美国10年期与2年期国债利差 | Percent | D | NSA | USA |  |
| `fred:T10Y3M` | 10-Year Treasury Constant Maturity Minus 3-Month Treasury Constant Maturity | 美国10年期与3个月期国债利差 | Percent | D | NSA | USA |  |
| `fred:T10YIE` | 10-Year Breakeven Inflation Rate | 美国10年期盈亏平衡通胀率 | Percent | D | NSA | USA |  |
| `fred:T5YIFR` | 5-Year, 5-Year Forward Inflation Expectation Rate | 美国5年后5年远期通胀预期 | Percent | D | NSA | USA |  |
| `fred:DFII10` | Market Yield on U.S. Treasury Securities at 10-Year Constant Maturity, Quoted on an Investment Basis, Inflation-Indexed | 美国10年期通胀保值国债实际收益率 | Percent | D | NSA | USA |  |
| `fred:MORTGAGE30US` | 30-Year Fixed Rate Mortgage Average in the United States | 美国30年期固定房贷平均利率 | Percent | W | NSA | USA |  |
| `fred:BAMLH0A0HYM2` | ICE BofA US High Yield Index Option-Adjusted Spread | 美国高收益债期权调整利差 | Percent | D | NSA | USA | ICE BofA indices on FRED keep only about three years of daily history (licensing). |
| `fred:BAMLC0A0CM` | ICE BofA US Corporate Index Option-Adjusted Spread | 美国投资级公司债期权调整利差 | Percent | D | NSA | USA | ICE BofA indices on FRED keep only about three years of daily history (licensing). |
| `fred:VIXCLS` | CBOE Volatility Index: VIX | 芝加哥期权交易所波动率指数VIX | Index | D | NSA | USA |  |
| `fred:SP500` | S&P 500 | 标普500指数 | Index | D | NSA | USA | FRED keeps only the latest ten years of daily values (licensing); price index without dividends. |
| `fred:DTWEXBGS` | Nominal Broad U.S. Dollar Index | 名义广义美元指数 | Index Jan 2006=100 | D | NSA | USA | Federal Reserve trade-weighted index (26 currencies), not the ICE DXY. |
| `fred:DEXUSEU` | U.S. Dollars to Euro Spot Exchange Rate | 欧元兑美元即期汇率 | U.S. Dollars to One Euro | D | NSA | EMU | Noon buying rates in New York; weekly/daily moves are noisy, compare monthly averages. |
| `fred:DEXJPUS` | Japanese Yen to U.S. Dollar Spot Exchange Rate | 美元兑日元即期汇率 | Japanese Yen to One U.S. Dollar | D | NSA | JPN | Noon buying rates in New York; weekly/daily moves are noisy, compare monthly averages. |
| `fred:DEXCHUS` | Chinese Yuan Renminbi to U.S. Dollar Spot Exchange Rate | 美元兑人民币即期汇率 | Chinese Yuan Renminbi to One U.S. Dollar | D | NSA | CHN | Noon buying rates in New York; weekly/daily moves are noisy, compare monthly averages. |
| `fred:DEXUSUK` | U.S. Dollars to U.K. Pound Sterling Spot Exchange Rate | 英镑兑美元即期汇率 | U.S. Dollars to One U.K. Pound Sterling | D | NSA | GBR | Noon buying rates in New York; weekly/daily moves are noisy, compare monthly averages. |
| `fred:DEXMXUS` | Mexican Pesos to U.S. Dollar Spot Exchange Rate | 美元兑墨西哥比索即期汇率 | Mexican Pesos to One U.S. Dollar | D | NSA | MEX | Noon buying rates in New York; weekly/daily moves are noisy, compare monthly averages. |
| `fred:DEXINUS` | Indian Rupees to U.S. Dollar Spot Exchange Rate | 美元兑印度卢比即期汇率 | Indian Rupees to One U.S. Dollar | D | NSA | IND | Noon buying rates in New York; weekly/daily moves are noisy, compare monthly averages. |
| `fred:DCOILWTICO` | Crude Oil Prices: West Texas Intermediate (WTI) - Cushing, Oklahoma | WTI原油现货价格 | Dollars per Barrel | D | NSA | WLD | Daily spot price (EIA); weekends and holidays are missing. |
| `fred:DCOILBRENTEU` | Crude Oil Prices: Brent - Europe | 布伦特原油现货价格 | Dollars per Barrel | D | NSA | WLD | Daily spot price (EIA); weekends and holidays are missing. |
| `fred:DHHNGSP` | Henry Hub Natural Gas Spot Price | 美国亨利港天然气现货价格 | Dollars per Million BTU | D | NSA | USA |  |
| `fred:GASREGW` | US Regular All Formulations Gas Price | 美国普通汽油零售均价 | Dollars per Gallon | W | NSA | USA |  |
| `fred:PNGASEUUSDM` | Global price of Natural gas, EU | 欧洲天然气价格（IMF） | U.S. Dollars per Million Metric British Thermal Unit | M | NSA | EMU | IMF primary commodity price (Netherlands TTF) mirrored on FRED; lags the IMF source by about two months (imf:PCPS/G001.PNGASEU.USD.M). |
| `fred:PCOPPUSDM` | Global price of Copper | 全球铜价（IMF） | U.S. Dollars per Metric Ton | M | NSA | WLD | IMF primary commodity price mirrored on FRED; lags the IMF source (imf:PCPS/G001.PCOPP.USD.M). |
| `fred:BOPGSTB` | Trade Balance: Goods and Services, Balance of Payments Basis | 美国商品和服务贸易差额 | Millions of Dollars | M | SA | USA | Negative values are deficits. |
| `fred:EXPGSC1` | Real Exports of Goods and Services | 美国实际商品和服务出口 | Billions of Chained 2017 Dollars | Q | SAAR | USA |  |
| `fred:IMPGSC1` | Real imports of goods and services | 美国实际商品和服务进口 | Billions of Chained 2017 Dollars | Q | SAAR | USA |  |
| `fred:GFDEGDQ188S` | Federal Debt: Total Public Debt as Percent of Gross Domestic Product | 美国联邦公共债务占GDP比率 | Percent of GDP | Q | SA | USA | Gross debt including intragovernmental holdings. |
| `fred:FYFSGDA188S` | Federal Surplus or Deficit [-] as Percent of Gross Domestic Product | 美国联邦财政盈余或赤字占GDP比率 | Percent of GDP | A | NSA | USA | Fiscal-year basis; negative values are deficits. |

## bls — U.S. Bureau of Labor Statistics

| Series id | Title | 中文 | Units | Freq | SA | Geo | Notes |
|---|---|---|---|---|---|---|---|
| `bls:CUUR0000SA0` | All items in U.S. city average, all urban consumers, not seasonally adjusted | 美国CPI-U全部项目（未季调） | Index 1982-84=100 | M | NSA | USA | Index level; the published 12-month inflation rate is the yoy change of this NSA series. |
| `bls:CUSR0000SA0` | All items in U.S. city average, all urban consumers, seasonally adjusted | 美国CPI-U全部项目（季调） | Index 1982-84=100 | M | SA | USA | Use for month-over-month changes; FRED mirror fred:CPIAUCSL. |
| `bls:CUUR0000SA0L1E` | All items less food and energy in U.S. city average, all urban consumers, not seasonally adjusted | 美国核心CPI（未季调） | Index 1982-84=100 | M | NSA | USA | The published 12-month core inflation rate is the yoy change of this NSA series. |
| `bls:CUSR0000SA0L1E` | All items less food and energy in U.S. city average, all urban consumers, seasonally adjusted | 美国核心CPI（季调） | Index 1982-84=100 | M | SA | USA | FRED mirror fred:CPILFESL. |
| `bls:SUUR0000SA0` | All items in U.S. city average, all urban consumers, chained, not seasonally adjusted | 美国链式CPI-U | Index Dec 1999=100 | M | NSA | USA | Latest months are preliminary and revised for ten to twelve months. |
| `bls:CUSR0000SAH1` | Shelter in U.S. city average, all urban consumers, seasonally adjusted | 美国CPI住房分项 | Index 1982-84=100 | M | SA | USA |  |
| `bls:CUSR0000SEHA` | Rent of primary residence in U.S. city average, all urban consumers, seasonally adjusted | 美国CPI主要住所租金 | Index 1982-84=100 | M | SA | USA |  |
| `bls:CUSR0000SAF11` | Food at home in U.S. city average, all urban consumers, seasonally adjusted | 美国CPI家庭食品 | Index 1982-84=100 | M | SA | USA |  |
| `bls:CUSR0000SAM` | Medical care in U.S. city average, all urban consumers, seasonally adjusted | 美国CPI医疗保健 | Index 1982-84=100 | M | SA | USA |  |
| `bls:CUSR0000SETA02` | Used cars and trucks in U.S. city average, all urban consumers, seasonally adjusted | 美国CPI二手车 | Index 1982-84=100 | M | SA | USA |  |
| `bls:CUSR0000SASLE` | Services less energy services in U.S. city average, all urban consumers, seasonally adjusted | 美国CPI核心服务（剔除能源服务） | Index 1982-84=100 | M | SA | USA |  |
| `bls:CUUR0000SETB01` | Gasoline (all types) in U.S. city average, all urban consumers, not seasonally adjusted | 美国CPI汽油 | Index 1982-84=100 | M | NSA | USA |  |
| `bls:CUUR0000SEHF01` | Electricity in U.S. city average, all urban consumers, not seasonally adjusted | 美国CPI电力 | Index 1982-84=100 | M | NSA | USA |  |
| `bls:APU000074714` | Gasoline, unleaded regular, per gallon/3.785 liters in U.S. city average, average price, not seasonally adjusted | 美国普通无铅汽油平均价格 | U.S. dollars per gallon | M | NSA | USA | Monthly average price; weekly retail prices are fred:GASREGW. |
| `bls:APU000072610` | Electricity per KWH in U.S. city average, average price, not seasonally adjusted | 美国居民电价（每千瓦时平均价格） | U.S. dollars per kilowatt-hour | M | NSA | USA |  |
| `bls:APU0000708111` | Eggs, grade A, large, per doz. in U.S. city average, average price, not seasonally adjusted | 美国A级大鸡蛋平均价格 | U.S. dollars per dozen | M | NSA | USA |  |
| `bls:APU0000703112` | Ground beef, 100% beef, per lb. (453.6 gm) in U.S. city average, average price, not seasonally adjusted | 美国碎牛肉平均价格 | U.S. dollars per pound | M | NSA | USA |  |
| `bls:WPSFD4` | PPI Commodity data for Final demand, seasonally adjusted | 美国PPI最终需求（季调） | Index Nov 2009=100 | M | SA | USA | Corrected label: the bundled bls-query catalog mislabels this id; the official BLS title is shown here. Not 'Finished Goods'. |
| `bls:WPUFD4` | PPI Commodity data for Final demand, not seasonally adjusted | 美国PPI最终需求（未季调） | Index Nov 2009=100 | M | NSA | USA | The published 12-month PPI change is the yoy change of this NSA series. |
| `bls:WPUFD49104` | PPI Commodity data for Final demand less foods and energy, not seasonally adjusted | 美国核心PPI（剔除食品和能源） | Index Apr 2010=100 | M | NSA | USA | Corrected label: the bundled bls-query catalog mislabels this id; the official BLS title is shown here. The catalog's WPSFD49104 'Finished Goods Less Food and Energy' is a different series. |
| `bls:WPUFD49116` | PPI Commodity data for Final demand less foods, energy, and trade services, not seasonally adjusted | 美国PPI最终需求（剔除食品、能源和贸易服务） | Index Aug 2013=100 | M | NSA | USA | Corrected label: the bundled bls-query catalog mislabels this id; the official BLS title is shown here. Not 'PPI: Final Demand' (that is WPUFD4). |
| `bls:WPU0561` | PPI Commodity data for Fuels and related products and power-Crude petroleum (domestic production), not seasonally adjusted | 美国PPI国产原油 | Index 1982=100 | M | NSA | USA |  |
| `bls:PCU221110221110` | PPI industry data for Electric power generation, not seasonally adjusted | 美国PPI发电行业 | Index Dec 2003=100 | M | NSA | USA |  |
| `bls:LNS14000000` | (Seas) Unemployment Rate | 美国失业率（16岁及以上，季调） | Percent | M | SA | USA | Household survey (CPS); FRED mirror fred:UNRATE. October 2025 missing (2025 federal shutdown). |
| `bls:LNU04000000` | (Unadj) Unemployment Rate | 美国失业率（未季调） | Percent | M | NSA | USA |  |
| `bls:LNS11300000` | (Seas) Labor Force Participation Rate | 美国劳动参与率 | Percent | M | SA | USA |  |
| `bls:LNS12300060` | (Seas) Employment-Population Ratio - 25-54 yrs. | 美国25-54岁就业人口比 | Percent | M | SA | USA |  |
| `bls:CES0000000001` | All employees, thousands, total nonfarm, seasonally adjusted | 美国非农就业人数 | Thousands of persons | M | SA | USA | Establishment survey; FRED mirror fred:PAYEMS. Latest two months are preliminary. |
| `bls:CES3000000001` | All employees, thousands, manufacturing, seasonally adjusted | 美国制造业就业人数 | Thousands of persons | M | SA | USA |  |
| `bls:CES0500000003` | Average hourly earnings of all employees, total private, seasonally adjusted | 美国私营部门平均时薪 | U.S. dollars per hour | M | SA | USA |  |
| `bls:CES0500000011` | Average weekly earnings of all employees, total private, seasonally adjusted | 美国私营部门平均周薪 | U.S. dollars per week | M | SA | USA |  |
| `bls:CES0500000002` | Average weekly hours of all employees, total private, seasonally adjusted | 美国私营部门平均每周工时 | Hours | M | SA | USA |  |
| `bls:JTS000000000000000JOL` | Job openings: total nonfarm, all size classes, level in thousands, seasonally adjusted | 美国职位空缺数（JOLTS） | Thousands | M | SA | USA | Published about five weeks after the reference month; FRED mirror fred:JTSJOL. |
| `bls:JTS000000000000000QUR` | Quits rate: total nonfarm, all size classes, seasonally adjusted | 美国离职率（主动辞职） | Percent | M | SA | USA |  |
| `bls:JTS000000000000000HIR` | Hires rate: total nonfarm, all size classes, seasonally adjusted | 美国招聘率 | Percent | M | SA | USA |  |
| `bls:JTS000000000000000LDR` | Layoffs and discharges rate: total nonfarm, all size classes, seasonally adjusted | 美国裁员率 | Percent | M | SA | USA |  |
| `bls:LASST060000000000003` | Unemployment rate: California, statewide, seasonally adjusted | 加州失业率 | Percent | M | SA | USA | LAUS state estimate; revised annually. |
| `bls:LASST480000000000003` | Unemployment rate: Texas, statewide, seasonally adjusted | 得克萨斯州失业率 | Percent | M | SA | USA | LAUS state estimate; revised annually. |
| `bls:LASST360000000000003` | Unemployment rate: New York, statewide, seasonally adjusted | 纽约州失业率 | Percent | M | SA | USA | LAUS state estimate; revised annually. |
| `bls:CIU1010000000000A` | Total compensation for all civilian workers, 12-month percent change, current dollars | 美国雇佣成本指数（总薪酬，同比） | Percent change over 12 months | Q | NSA | USA | Id suffix encodes the measure: A = 12-month percent change, I = index, Q = 3-month percent change. |
| `bls:CIU1010000000000I` | Total compensation for all civilian workers, current dollar index | 美国雇佣成本指数（总薪酬，指数） | Index Dec 2005=100 | Q | NSA | USA |  |
| `bls:PRS85006092` | Nonfarm Business: Labor productivity (output per hour), % change from previous quarter | 美国非农企业劳动生产率（环比折年率） | Percent change from previous quarter at annual rate | Q | SA | USA |  |
| `bls:PRS85006112` | Nonfarm Business: Unit labor costs, % change from previous quarter | 美国非农企业单位劳动力成本（环比折年率） | Percent change from previous quarter at annual rate | Q | SA | USA |  |
| `bls:EIUIR` | Monthly import price index for BEA End Use, All commodities, not seasonally adjusted | 美国进口价格指数 | Index 2000=100 | M | NSA | USA |  |
| `bls:EIUIQ` | Monthly export price index for BEA End Use, All commodities, not seasonally adjusted | 美国出口价格指数 | Index 2000=100 | M | NSA | USA |  |

## bis — Bank for International Settlements (BIS)

| Series id | Title | 中文 | Units | Freq | SA | Geo | Notes |
|---|---|---|---|---|---|---|---|
| `bis:WS_CBPOL/M.US` | Central bank policy rates - United States - Monthly - End of period | 美国央行政策利率 | Per cent per year | M |  | USA | For the United States BIS reports the midpoint of the federal funds target range; fred:DFEDTARU is the upper limit. |
| `bis:WS_CBPOL/M.XM` | Central bank policy rates - Euro area - Monthly - End of period | 欧元区央行政策利率 | Per cent per year | M |  | EMU |  |
| `bis:WS_CBPOL/M.GB` | Central bank policy rates - United Kingdom - Monthly - End of period | 英国央行政策利率 | Per cent per year | M |  | GBR |  |
| `bis:WS_CBPOL/M.JP` | Central bank policy rates - Japan - Monthly - End of period | 日本央行政策利率 | Per cent per year | M |  | JPN |  |
| `bis:WS_CBPOL/M.CN` | Central bank policy rates - China - Monthly - End of period | 中国央行政策利率 | Per cent per year | M |  | CHN |  |
| `bis:WS_CBPOL/M.IN` | Central bank policy rates - India - Monthly - End of period | 印度央行政策利率 | Per cent per year | M |  | IND |  |
| `bis:WS_CBPOL/M.BR` | Central bank policy rates - Brazil - Monthly - End of period | 巴西央行政策利率 | Per cent per year | M |  | BRA |  |
| `bis:WS_CBPOL/M.CA` | Central bank policy rates - Canada - Monthly - End of period | 加拿大央行政策利率 | Per cent per year | M |  | CAN |  |
| `bis:WS_CBPOL/M.KR` | Central bank policy rates - Korea - Monthly - End of period | 韩国央行政策利率 | Per cent per year | M |  | KOR |  |
| `bis:WS_CBPOL/M.AU` | Central bank policy rates - Australia - Monthly - End of period | 澳大利亚央行政策利率 | Per cent per year | M |  | AUS |  |
| `bis:WS_CBPOL/M.CH` | Central bank policy rates - Switzerland - Monthly - End of period | 瑞士央行政策利率 | Per cent per year | M |  | CHE |  |
| `bis:WS_CBPOL/M.MX` | Central bank policy rates - Mexico - Monthly - End of period | 墨西哥央行政策利率 | Per cent per year | M |  | MEX |  |
| `bis:WS_CREDIT_GAP/Q.US.P.A.C` | Credit-to-GDP gaps (actual-trend): United States - Private non-financial sector | 美国信贷/GDP缺口 | Percentage points of GDP | Q |  | USA | Above 10 percentage points is the Basel early-warning zone; one-sided HP trend. |
| `bis:WS_CREDIT_GAP/Q.XM.P.A.C` | Credit-to-GDP gaps (actual-trend): Euro area - Private non-financial sector | 欧元区信贷/GDP缺口 | Percentage points of GDP | Q |  | EMU | Above 10 percentage points is the Basel early-warning zone; one-sided HP trend. |
| `bis:WS_CREDIT_GAP/Q.GB.P.A.C` | Credit-to-GDP gaps (actual-trend): United Kingdom - Private non-financial sector | 英国信贷/GDP缺口 | Percentage points of GDP | Q |  | GBR | Above 10 percentage points is the Basel early-warning zone; one-sided HP trend. |
| `bis:WS_CREDIT_GAP/Q.JP.P.A.C` | Credit-to-GDP gaps (actual-trend): Japan - Private non-financial sector | 日本信贷/GDP缺口 | Percentage points of GDP | Q |  | JPN | Above 10 percentage points is the Basel early-warning zone; one-sided HP trend. |
| `bis:WS_CREDIT_GAP/Q.CN.P.A.C` | Credit-to-GDP gaps (actual-trend): China - Private non-financial sector | 中国信贷/GDP缺口 | Percentage points of GDP | Q |  | CHN | Above 10 percentage points is the Basel early-warning zone; one-sided HP trend. |
| `bis:WS_TC/Q.US.P.A.M.770.A` | United States - Credit to Private non-financial sector from All sectors at Market value - Percentage of GDP - Adjusted for breaks | 美国私人非金融部门信贷占GDP比率 | Percentage of GDP | Q |  | USA |  |
| `bis:WS_TC/Q.US.H.A.M.770.A` | United States - Credit to Households and NPISHs from All sectors at Market value - Percentage of GDP - Adjusted for breaks | 美国居民部门信贷占GDP比率 | Percentage of GDP | Q |  | USA |  |
| `bis:WS_TC/Q.US.G.A.M.770.A` | United States - Credit to General government from All sectors at Market value - Percentage of GDP - Adjusted for breaks | 美国政府部门信贷占GDP比率 | Percentage of GDP | Q |  | USA | Market value of government debt; differs from the face-value debt-to-GDP ratio. |
| `bis:WS_TC/Q.CN.P.A.M.770.A` | China - Credit to Private non-financial sector from All sectors at Market value - Percentage of GDP - Adjusted for breaks | 中国私人非金融部门信贷占GDP比率 | Percentage of GDP | Q |  | CHN |  |
| `bis:WS_TC/Q.CN.H.A.M.770.A` | China - Credit to Households and NPISHs from All sectors at Market value - Percentage of GDP - Adjusted for breaks | 中国居民部门信贷占GDP比率 | Percentage of GDP | Q |  | CHN |  |
| `bis:WS_TC/Q.JP.G.A.M.770.A` | Japan - Credit to General government from All sectors at Market value - Percentage of GDP - Adjusted for breaks | 日本政府部门信贷占GDP比率 | Percentage of GDP | Q |  | JPN |  |
| `bis:WS_DSR/Q.US.P` | Debt service ratios: United States - Private non-financial sector | 美国私人非金融部门偿债比率 | Per cent of income | Q |  | USA |  |
| `bis:WS_DSR/Q.US.H` | Debt service ratios: United States - Households and NPISHs | 美国居民部门偿债比率 | Per cent of income | Q |  | USA |  |
| `bis:WS_DSR/Q.CN.P` | Debt service ratios: China - Private non-financial sector | 中国私人非金融部门偿债比率 | Per cent of income | Q |  | CHN |  |
| `bis:WS_DSR/Q.GB.P` | Debt service ratios: United Kingdom - Private non-financial sector | 英国私人非金融部门偿债比率 | Per cent of income | Q |  | GBR |  |
| `bis:WS_SPP/Q.US.R.628` | Residential property prices: United States - Real - Index, 2010 = 100 | 美国实际住宅价格指数 | Index, 2010 = 100 | Q |  | USA |  |
| `bis:WS_SPP/Q.US.N.628` | Residential property prices: United States - Nominal - Index, 2010 = 100 | 美国名义住宅价格指数 | Index, 2010 = 100 | Q |  | USA |  |
| `bis:WS_SPP/Q.CN.R.628` | Residential property prices: China - Real - Index, 2010 = 100 | 中国实际住宅价格指数 | Index, 2010 = 100 | Q |  | CHN |  |
| `bis:WS_SPP/Q.GB.R.628` | Residential property prices: United Kingdom - Real - Index, 2010 = 100 | 英国实际住宅价格指数 | Index, 2010 = 100 | Q |  | GBR |  |
| `bis:WS_XRU/M.JP.JPY.A` | Exchange rates against USD Japan - Yen - Monthly - Average of observations through period | 日元兑美元汇率（月均） | Yen per US dollar | M |  | JPN |  |
| `bis:WS_XRU/M.CN.CNY.A` | Exchange rates against USD China - Renminbi - Monthly - Average of observations through period | 人民币兑美元汇率（月均） | Renminbi per US dollar | M |  | CHN |  |
| `bis:WS_XRU/M.XM.EUR.A` | Exchange rates against USD Euro area - Euro - Monthly - Average of observations through period | 欧元兑美元汇率（月均） | Euro per US dollar | M |  | EMU | Quoted as euros per US dollar (the inverse of the usual EUR/USD quote). |
| `bis:WS_XRU/M.GB.GBP.A` | Exchange rates against USD United Kingdom - Pound (sterling) - Monthly - Average of observations through period | 英镑兑美元汇率（月均） | Pounds sterling per US dollar | M |  | GBR | Quoted as pounds per US dollar (the inverse of the usual GBP/USD quote). |
| `bis:WS_XRU/M.IN.INR.A` | Exchange rates against USD India - Indian rupee - Monthly - Average of observations through period | 印度卢比兑美元汇率（月均） | Indian rupees per US dollar | M |  | IND |  |
| `bis:WS_EER/M.R.B.US` | Effective exchange rates: United States - Real - Broad (64 economies) | 美元实际有效汇率 | Index, 2020 = 100 | M |  | USA |  |
| `bis:WS_EER/M.N.B.US` | Effective exchange rates: United States - Nominal - Broad (64 economies) | 美元名义有效汇率 | Index, 2020 = 100 | M |  | USA |  |
| `bis:WS_EER/M.R.B.CN` | Effective exchange rates: China - Real - Broad (64 economies) | 人民币实际有效汇率 | Index, 2020 = 100 | M |  | CHN |  |
| `bis:WS_EER/M.R.B.XM` | Effective exchange rates: Euro area - Real - Broad (64 economies) | 欧元实际有效汇率 | Index, 2020 = 100 | M |  | EMU |  |
| `bis:WS_EER/M.R.B.JP` | Effective exchange rates: Japan - Real - Broad (64 economies) | 日元实际有效汇率 | Index, 2020 = 100 | M |  | JPN |  |
| `bis:WS_LONG_CPI/M.US.771` | Consumer prices: United States - Year-on-year changes, in per cent | 美国CPI同比（BIS） | Per cent, year-on-year change | M |  | USA |  |
| `bis:WS_LONG_CPI/M.CN.771` | Consumer prices: China - Year-on-year changes, in per cent | 中国CPI同比（BIS） | Per cent, year-on-year change | M |  | CHN |  |
| `bis:WS_LONG_CPI/M.XM.771` | Consumer prices: Euro area - Year-on-year changes, in per cent | 欧元区CPI同比（BIS） | Per cent, year-on-year change | M |  | EMU | Euro-area HICP as compiled by the BIS. |
| `bis:WS_LONG_CPI/M.JP.771` | Consumer prices: Japan - Year-on-year changes, in per cent | 日本CPI同比（BIS） | Per cent, year-on-year change | M |  | JPN |  |
| `bis:WS_CBTA/M.US.B.XDC.USD.N` | United States - Central bank, assets, total, BIS-spliced | 美联储总资产（BIS） | US dollar, billions | M |  | USA |  |
| `bis:WS_CBTA/M.XM.B.XDC.EUR.N` | Euro area - Central bank, assets, total, BIS-spliced | 欧元体系总资产 | Euro, billions | M |  | EMU |  |
| `bis:WS_CBTA/M.JP.B.XDC.JPY.N` | Japan - Central bank, assets, total, BIS-spliced | 日本央行总资产 | Japanese yen, billions | M |  | JPN |  |
| `bis:WS_CBTA/M.CN.B.XDC.CNY.N` | China - Central bank, assets, total, BIS-spliced | 中国人民银行总资产 | Chinese yuan renminbi, billions | M |  | CHN |  |
| `bis:WS_GLI/Q.USD.3P.N.A.I.B.USD` | USD denominated credit (bank loans & debt securities) to non-bank borrowers located outside the US | 美国境外非银行借款人的美元信贷 | US dollar, millions | Q |  | WLD |  |

## imf — International Monetary Fund (IMF)

| Series id | Title | 中文 | Units | Freq | SA | Geo | Notes |
|---|---|---|---|---|---|---|---|
| `imf:WEO/G001.NGDP_RPCH.A` | Gross domestic product (GDP), Constant prices, Percent change: World | 世界实际GDP增长率（IMF WEO） | Percent change | A |  | WLD | IMF World Economic Outlook: values after the latest completed year are IMF projections (horizon about five years). |
| `imf:WEO/G163.NGDP_RPCH.A` | Gross domestic product (GDP), Constant prices, Percent change: Euro Area (EA) | 欧元区实际GDP增长率（IMF WEO） | Percent change | A |  | EMU | IMF World Economic Outlook: values after the latest completed year are IMF projections (horizon about five years). |
| `imf:WEO/USA.NGDP_RPCH.A` | Gross domestic product (GDP), Constant prices, Percent change: United States | 美国实际GDP增长率（IMF WEO） | Percent change | A |  | USA | IMF World Economic Outlook: values after the latest completed year are IMF projections (horizon about five years). Same values as wb:IMF_WEO_NGDP_RPCH/USA, which is faster. |
| `imf:WEO/G001.PCPIPCH.A` | All Items, Consumer price index (CPI), Period average, percent change: World | 世界CPI通胀率（IMF WEO） | Percent change | A |  | WLD | IMF World Economic Outlook: values after the latest completed year are IMF projections (horizon about five years). |
| `imf:WEO/G163.PCPIPCH.A` | All Items, Consumer price index (CPI), Period average, percent change: Euro Area (EA) | 欧元区CPI通胀率（IMF WEO） | Percent change | A |  | EMU | IMF World Economic Outlook: values after the latest completed year are IMF projections (horizon about five years). |
| `imf:WEO/G163.LUR.A` | Unemployment rate: Euro Area (EA) | 欧元区失业率（IMF WEO） | Percent of labor force | A |  | EMU | IMF World Economic Outlook: values after the latest completed year are IMF projections (horizon about five years). |
| `imf:WEO/G001.NGDPD.A` | Gross domestic product (GDP), Current prices, US dollar: World | 世界名义GDP（美元，IMF WEO） | U.S. dollars | A |  | WLD | IMF World Economic Outlook: values after the latest completed year are IMF projections (horizon about five years). Values are whole U.S. dollars (IMF SCALE 9 is a display hint); divide by 1e12 for trillions. |
| `imf:WEO/G001.POILBRE.A` | Brent crude, Unit prices, US dollars per barrel: World (WEO assumption) | 布伦特油价假设（IMF WEO） | U.S. dollars per barrel | A |  | WLD | WEO baseline oil-price assumption (futures-based), not an IMF price forecast in the usual sense. |
| `imf:WEO/G001.TRADEPCH.A` | Trade of goods and services, Volume, Percent change: World | 世界贸易量增长率（IMF WEO） | Percent change | A |  | WLD | IMF World Economic Outlook: values after the latest completed year are IMF projections (horizon about five years). |
| `imf:WEO_2026_APR_VINTAGE/USA.NGDP_RPCH.A` | Gross domestic product (GDP), Constant prices, Percent change: United States (WEO April 2026 vintage) | 美国GDP增长率（IMF WEO 2026年4月版） | Percent change | A |  | USA | Frozen WEO vintage: compare with the live imf:WEO series to see how the IMF forecast was revised. No data.imf.org page per vintage; the WEO dataset page is cited. |
| `imf:WEO_2026_APR_VINTAGE/CHN.NGDP_RPCH.A` | Gross domestic product (GDP), Constant prices, Percent change: China (WEO April 2026 vintage) | 中国GDP增长率（IMF WEO 2026年4月版） | Percent change | A |  | CHN | Frozen WEO vintage: compare with the live imf:WEO series to see how the IMF forecast was revised. No data.imf.org page per vintage; the WEO dataset page is cited. |
| `imf:WEO_2025_OCT_VINTAGE/USA.NGDP_RPCH.A` | Gross domestic product (GDP), Constant prices, Percent change: United States (WEO October 2025 vintage) | 美国GDP增长率（IMF WEO 2025年10月版） | Percent change | A |  | USA | Frozen WEO vintage: compare with the live imf:WEO series to see how the IMF forecast was revised. No data.imf.org page per vintage; the WEO dataset page is cited. |
| `imf:WEO_2025_OCT_VINTAGE/CHN.NGDP_RPCH.A` | Gross domestic product (GDP), Constant prices, Percent change: China (WEO October 2025 vintage) | 中国GDP增长率（IMF WEO 2025年10月版） | Percent change | A |  | CHN | Frozen WEO vintage: compare with the live imf:WEO series to see how the IMF forecast was revised. No data.imf.org page per vintage; the WEO dataset page is cited. |
| `imf:PCPS/G001.POILBRE.USD.M` | Brent Crude, US dollars per barrel, Unit prices | 布伦特原油价格（IMF月均） | U.S. dollars per barrel | M |  | WLD | IMF Primary Commodity Prices, monthly average of daily quotes. |
| `imf:PCPS/G001.POILWTI.USD.M` | WTI Crude, US dollars per barrel, Unit prices | WTI原油价格（IMF月均） | U.S. dollars per barrel | M |  | WLD | IMF Primary Commodity Prices, monthly average of daily quotes. |
| `imf:PCPS/G001.PNGASEU.USD.M` | Natural gas, EU, US dollars per million metric British thermal units of gas, Unit prices | 欧洲天然气价格（TTF，IMF月均） | U.S. dollars per million British thermal units | M |  | WLD | IMF Primary Commodity Prices, monthly average of daily quotes. Netherlands TTF day-ahead. |
| `imf:PCPS/G001.PNGASJP.USD.M` | LNG, Asia, US dollars per million metric British thermal units of gas, Unit prices | 亚洲液化天然气价格（IMF月均） | U.S. dollars per million British thermal units | M |  | WLD | IMF Primary Commodity Prices, monthly average of daily quotes. |
| `imf:PCPS/G001.PCOALAU.USD.M` | Coal, Australia, US dollars per metric tonne, Unit prices | 澳大利亚动力煤价格（IMF月均） | U.S. dollars per metric ton | M |  | WLD | IMF Primary Commodity Prices, monthly average of daily quotes. |
| `imf:PCPS/G001.PURAN.USD.M` | Uranium, US dollars per pound, Unit prices | 铀价格（IMF月均） | U.S. dollars per pound | M |  | WLD | IMF Primary Commodity Prices, monthly average of daily quotes. |
| `imf:PCPS/G001.PCOPP.USD.M` | Copper, US dollars per metric tonne, Unit prices | 铜价格（IMF月均） | U.S. dollars per metric ton | M |  | WLD | IMF Primary Commodity Prices, monthly average of daily quotes. |
| `imf:PCPS/G001.PALUM.USD.M` | Aluminum, US dollars per metric tonne, Unit prices | 铝价格（IMF月均） | U.S. dollars per metric ton | M |  | WLD | IMF Primary Commodity Prices, monthly average of daily quotes. |
| `imf:PCPS/G001.PNICK.USD.M` | Nickel, US dollars per metric tonne, Unit prices | 镍价格（IMF月均） | U.S. dollars per metric ton | M |  | WLD | IMF Primary Commodity Prices, monthly average of daily quotes. |
| `imf:PCPS/G001.PCOBA.USD.M` | Cobalt, US dollars per pound, Unit prices | 钴价格（IMF月均） | U.S. dollars per metric ton | M |  | WLD | IMF label says per pound, but the series description (LME spot, USD/ton) and the magnitude are US dollars per metric ton. |
| `imf:PCPS/G001.PLITH.USD.M` | Lithium, 99%, Battery Grade, Unit prices | 锂价格（电池级，IMF月均） | U.S. dollars (IMF states no unit) | M |  | WLD | Lithium metal 99% battery grade; IMF publishes no unit (magnitude consistent with US dollars per metric ton). Not lithium carbonate: compare changes, not levels, with carbonate quotes. |
| `imf:PCPS/G001.PIORECR.USD.M` | Iron Ore, US dollars per metric tonne, Unit prices | 铁矿石价格（IMF月均） | U.S. dollars per metric ton | M |  | WLD | IMF Primary Commodity Prices, monthly average of daily quotes. China import fines 62% Fe. |
| `imf:PCPS/G001.PGOLD.USD.M` | Gold, US dollars per troy ounce of gold, Unit prices | 黄金价格（IMF月均） | U.S. dollars per troy ounce | M |  | WLD | IMF Primary Commodity Prices, monthly average of daily quotes. |
| `imf:PCPS/G001.PWHEAMT.USD.M` | Wheat, US dollars per metric tonne, Unit prices | 小麦价格（IMF月均） | U.S. dollars per metric ton | M |  | WLD | IMF Primary Commodity Prices, monthly average of daily quotes. |
| `imf:PCPS/G001.PMAIZMT.USD.M` | Corn, US dollars per metric tonne, Unit prices | 玉米价格（IMF月均） | U.S. dollars per metric ton | M |  | WLD | IMF Primary Commodity Prices, monthly average of daily quotes. |
| `imf:PCPS/G001.PSOYB.USD.M` | Soybeans, US dollars per metric tonne, Unit prices | 大豆价格（IMF月均） | U.S. dollars per metric ton | M |  | WLD | IMF Primary Commodity Prices, monthly average of daily quotes. |
| `imf:PCPS/G001.PALLFNF.INDEX.M` | All index, Commodity price index, Index, 2016=100 | IMF全部大宗商品价格指数 | Index 2016=100 | M |  | WLD | IMF Primary Commodity Prices, monthly average of daily quotes. |
| `imf:PCPS/G001.PNRG.INDEX.M` | Energy index, Commodity price index, Index, 2016=100 | IMF能源价格指数 | Index 2016=100 | M |  | WLD | IMF Primary Commodity Prices, monthly average of daily quotes. |
| `imf:PCPS/G001.PMETA.INDEX.M` | Base Metals index, Commodity price index, Index, 2016=100 | IMF基本金属价格指数 | Index 2016=100 | M |  | WLD | IMF Primary Commodity Prices, monthly average of daily quotes. |
| `imf:PCPS/G001.PFOOD.INDEX.M` | Food index, Commodity price index, Index, 2016=100 | IMF食品价格指数 | Index 2016=100 | M |  | WLD | IMF Primary Commodity Prices, monthly average of daily quotes. |
| `imf:CPI/USA.CPI._T.YOY_PCH_PA_PT.M` | Consumer price index (CPI), All Items, Period average, Year-over-year (YOY) percent change: United States | 美国CPI同比（IMF） | Percent change, year over year | M |  | USA | IMF CPI dataset; the latest month lags national releases by one to two months. |
| `imf:CPI/CHN.CPI._T.YOY_PCH_PA_PT.M` | Consumer price index (CPI), All Items, Period average, Year-over-year (YOY) percent change: China | 中国CPI同比（IMF） | Percent change, year over year | M |  | CHN | IMF CPI dataset; the latest month lags national releases by one to two months. |
| `imf:CPI/DEU.CPI._T.YOY_PCH_PA_PT.M` | Consumer price index (CPI), All Items, Period average, Year-over-year (YOY) percent change: Germany | 德国CPI同比（IMF） | Percent change, year over year | M |  | DEU | IMF CPI dataset; the latest month lags national releases by one to two months. |
| `imf:CPI/JPN.CPI._T.YOY_PCH_PA_PT.M` | Consumer price index (CPI), All Items, Period average, Year-over-year (YOY) percent change: Japan | 日本CPI同比（IMF） | Percent change, year over year | M |  | JPN | IMF CPI dataset; the latest month lags national releases by one to two months. |
| `imf:CPI/GBR.CPI._T.YOY_PCH_PA_PT.M` | Consumer price index (CPI), All Items, Period average, Year-over-year (YOY) percent change: United Kingdom | 英国CPI同比（IMF） | Percent change, year over year | M |  | GBR | IMF CPI dataset; the latest month lags national releases by one to two months. |
| `imf:CPI/IND.CPI._T.YOY_PCH_PA_PT.M` | Consumer price index (CPI), All Items, Period average, Year-over-year (YOY) percent change: India | 印度CPI同比（IMF） | Percent change, year over year | M |  | IND | IMF CPI dataset; the latest month lags national releases by one to two months. |
| `imf:CPI/BRA.CPI._T.YOY_PCH_PA_PT.M` | Consumer price index (CPI), All Items, Period average, Year-over-year (YOY) percent change: Brazil | 巴西CPI同比（IMF） | Percent change, year over year | M |  | BRA | IMF CPI dataset; the latest month lags national releases by one to two months. |

## wb — World Bank Data360

| Series id | Title | 中文 | Units | Freq | SA | Geo | Notes |
|---|---|---|---|---|---|---|---|
| `wb:IMF_WEO_NGDP_RPCH/USA` | Gross domestic product (GDP), Constant prices, Percent change: United States | 美国实际GDP增长率（IMF WEO） | Percent change | A |  | USA | IMF WEO via Data360 (latest vintage): values after the latest completed year are IMF projections to 2031. Countries only; world and euro-area aggregates are imf:WEO/G001 and G163. |
| `wb:IMF_WEO_NGDP_RPCH/CHN` | Gross domestic product (GDP), Constant prices, Percent change: China | 中国实际GDP增长率（IMF WEO） | Percent change | A |  | CHN | IMF WEO via Data360 (latest vintage): values after the latest completed year are IMF projections to 2031. Countries only; world and euro-area aggregates are imf:WEO/G001 and G163. |
| `wb:IMF_WEO_NGDP_RPCH/JPN` | Gross domestic product (GDP), Constant prices, Percent change: Japan | 日本实际GDP增长率（IMF WEO） | Percent change | A |  | JPN | IMF WEO via Data360 (latest vintage): values after the latest completed year are IMF projections to 2031. Countries only; world and euro-area aggregates are imf:WEO/G001 and G163. |
| `wb:IMF_WEO_NGDP_RPCH/DEU` | Gross domestic product (GDP), Constant prices, Percent change: Germany | 德国实际GDP增长率（IMF WEO） | Percent change | A |  | DEU | IMF WEO via Data360 (latest vintage): values after the latest completed year are IMF projections to 2031. Countries only; world and euro-area aggregates are imf:WEO/G001 and G163. |
| `wb:IMF_WEO_NGDP_RPCH/GBR` | Gross domestic product (GDP), Constant prices, Percent change: United Kingdom | 英国实际GDP增长率（IMF WEO） | Percent change | A |  | GBR | IMF WEO via Data360 (latest vintage): values after the latest completed year are IMF projections to 2031. Countries only; world and euro-area aggregates are imf:WEO/G001 and G163. |
| `wb:IMF_WEO_NGDP_RPCH/IND` | Gross domestic product (GDP), Constant prices, Percent change: India | 印度实际GDP增长率（IMF WEO） | Percent change | A |  | IND | IMF WEO via Data360 (latest vintage): values after the latest completed year are IMF projections to 2031. Countries only; world and euro-area aggregates are imf:WEO/G001 and G163. |
| `wb:IMF_WEO_PCPIPCH/USA` | All Items, Consumer price index (CPI), Period average, percent change: United States | 美国CPI通胀率（IMF WEO） | Percent change | A |  | USA | IMF WEO via Data360 (latest vintage): values after the latest completed year are IMF projections to 2031. Countries only; world and euro-area aggregates are imf:WEO/G001 and G163. |
| `wb:IMF_WEO_PCPIPCH/CHN` | All Items, Consumer price index (CPI), Period average, percent change: China | 中国CPI通胀率（IMF WEO） | Percent change | A |  | CHN | IMF WEO via Data360 (latest vintage): values after the latest completed year are IMF projections to 2031. Countries only; world and euro-area aggregates are imf:WEO/G001 and G163. |
| `wb:IMF_WEO_PCPIPCH/JPN` | All Items, Consumer price index (CPI), Period average, percent change: Japan | 日本CPI通胀率（IMF WEO） | Percent change | A |  | JPN | IMF WEO via Data360 (latest vintage): values after the latest completed year are IMF projections to 2031. Countries only; world and euro-area aggregates are imf:WEO/G001 and G163. |
| `wb:IMF_WEO_PCPIPCH/DEU` | All Items, Consumer price index (CPI), Period average, percent change: Germany | 德国CPI通胀率（IMF WEO） | Percent change | A |  | DEU | IMF WEO via Data360 (latest vintage): values after the latest completed year are IMF projections to 2031. Countries only; world and euro-area aggregates are imf:WEO/G001 and G163. |
| `wb:IMF_WEO_PCPIPCH/GBR` | All Items, Consumer price index (CPI), Period average, percent change: United Kingdom | 英国CPI通胀率（IMF WEO） | Percent change | A |  | GBR | IMF WEO via Data360 (latest vintage): values after the latest completed year are IMF projections to 2031. Countries only; world and euro-area aggregates are imf:WEO/G001 and G163. |
| `wb:IMF_WEO_PCPIPCH/IND` | All Items, Consumer price index (CPI), Period average, percent change: India | 印度CPI通胀率（IMF WEO） | Percent change | A |  | IND | IMF WEO via Data360 (latest vintage): values after the latest completed year are IMF projections to 2031. Countries only; world and euro-area aggregates are imf:WEO/G001 and G163. |
| `wb:IMF_WEO_LUR/USA` | Unemployment rate: United States | 美国失业率（IMF WEO） | Percent of labor force | A |  | USA | IMF WEO via Data360 (latest vintage): values after the latest completed year are IMF projections to 2031. Countries only; world and euro-area aggregates are imf:WEO/G001 and G163. Data360 labels the unit 'Percentage of… |
| `wb:IMF_WEO_LUR/CHN` | Unemployment rate: China | 中国失业率（IMF WEO） | Percent of labor force | A |  | CHN | IMF WEO via Data360 (latest vintage): values after the latest completed year are IMF projections to 2031. Countries only; world and euro-area aggregates are imf:WEO/G001 and G163. Data360 labels the unit 'Percentage of… |
| `wb:IMF_WEO_LUR/JPN` | Unemployment rate: Japan | 日本失业率（IMF WEO） | Percent of labor force | A |  | JPN | IMF WEO via Data360 (latest vintage): values after the latest completed year are IMF projections to 2031. Countries only; world and euro-area aggregates are imf:WEO/G001 and G163. Data360 labels the unit 'Percentage of… |
| `wb:IMF_WEO_LUR/DEU` | Unemployment rate: Germany | 德国失业率（IMF WEO） | Percent of labor force | A |  | DEU | IMF WEO via Data360 (latest vintage): values after the latest completed year are IMF projections to 2031. Countries only; world and euro-area aggregates are imf:WEO/G001 and G163. Data360 labels the unit 'Percentage of… |
| `wb:IMF_WEO_LUR/GBR` | Unemployment rate: United Kingdom | 英国失业率（IMF WEO） | Percent of labor force | A |  | GBR | IMF WEO via Data360 (latest vintage): values after the latest completed year are IMF projections to 2031. Countries only; world and euro-area aggregates are imf:WEO/G001 and G163. Data360 labels the unit 'Percentage of… |
| `wb:IMF_WEO_GGXWDG_NGDP/USA` | Gross debt, General government, Percent of GDP: United States | 美国政府总债务占GDP比率（IMF WEO） | Percent of GDP | A |  | USA | IMF WEO via Data360 (latest vintage): values after the latest completed year are IMF projections to 2031. Countries only; world and euro-area aggregates are imf:WEO/G001 and G163. |
| `wb:IMF_WEO_GGXWDG_NGDP/CHN` | Gross debt, General government, Percent of GDP: China | 中国政府总债务占GDP比率（IMF WEO） | Percent of GDP | A |  | CHN | IMF WEO via Data360 (latest vintage): values after the latest completed year are IMF projections to 2031. Countries only; world and euro-area aggregates are imf:WEO/G001 and G163. |
| `wb:IMF_WEO_GGXWDG_NGDP/JPN` | Gross debt, General government, Percent of GDP: Japan | 日本政府总债务占GDP比率（IMF WEO） | Percent of GDP | A |  | JPN | IMF WEO via Data360 (latest vintage): values after the latest completed year are IMF projections to 2031. Countries only; world and euro-area aggregates are imf:WEO/G001 and G163. |
| `wb:IMF_WEO_GGXWDG_NGDP/GBR` | Gross debt, General government, Percent of GDP: United Kingdom | 英国政府总债务占GDP比率（IMF WEO） | Percent of GDP | A |  | GBR | IMF WEO via Data360 (latest vintage): values after the latest completed year are IMF projections to 2031. Countries only; world and euro-area aggregates are imf:WEO/G001 and G163. |
| `wb:IMF_WEO_BCA_NGDPD/USA` | Current account balance (credit less debit), Percent of GDP: United States | 美国经常账户余额占GDP比率（IMF WEO） | Percent of GDP | A |  | USA | IMF WEO via Data360 (latest vintage): values after the latest completed year are IMF projections to 2031. Countries only; world and euro-area aggregates are imf:WEO/G001 and G163. |
| `wb:IMF_WEO_BCA_NGDPD/CHN` | Current account balance (credit less debit), Percent of GDP: China | 中国经常账户余额占GDP比率（IMF WEO） | Percent of GDP | A |  | CHN | IMF WEO via Data360 (latest vintage): values after the latest completed year are IMF projections to 2031. Countries only; world and euro-area aggregates are imf:WEO/G001 and G163. |
| `wb:IMF_WEO_BCA_NGDPD/DEU` | Current account balance (credit less debit), Percent of GDP: Germany | 德国经常账户余额占GDP比率（IMF WEO） | Percent of GDP | A |  | DEU | IMF WEO via Data360 (latest vintage): values after the latest completed year are IMF projections to 2031. Countries only; world and euro-area aggregates are imf:WEO/G001 and G163. |
| `wb:IMF_WEO_BCA_NGDPD/JPN` | Current account balance (credit less debit), Percent of GDP: Japan | 日本经常账户余额占GDP比率（IMF WEO） | Percent of GDP | A |  | JPN | IMF WEO via Data360 (latest vintage): values after the latest completed year are IMF projections to 2031. Countries only; world and euro-area aggregates are imf:WEO/G001 and G163. |
| `wb:IMF_WEO_NGDPD/USA` | Gross domestic product (GDP), Current prices, US dollar: United States | 美国名义GDP（美元，IMF WEO） | U.S. dollars | A |  | USA | IMF WEO via Data360 (latest vintage): values after the latest completed year are IMF projections to 2031. Countries only; world and euro-area aggregates are imf:WEO/G001 and G163. Values are whole U.S. dollars although… |
| `wb:IMF_WEO_NGDPD/CHN` | Gross domestic product (GDP), Current prices, US dollar: China | 中国名义GDP（美元，IMF WEO） | U.S. dollars | A |  | CHN | IMF WEO via Data360 (latest vintage): values after the latest completed year are IMF projections to 2031. Countries only; world and euro-area aggregates are imf:WEO/G001 and G163. Values are whole U.S. dollars although… |
| `wb:WB_GEP_NYGDPMKTPKDZ/USA` | GDP growth, constant (average 2010-19 prices and market exchange rates): United States | 美国GDP增长率（世界银行全球经济展望） | Percent change per annum | A |  | USA | World Bank Global Economic Prospects: short window (about five years) whose final years are World Bank forecasts. No world aggregate in Data360. |
| `wb:WB_GEP_NYGDPMKTPKDZ/CHN` | GDP growth, constant (average 2010-19 prices and market exchange rates): China | 中国GDP增长率（世界银行全球经济展望） | Percent change per annum | A |  | CHN | World Bank Global Economic Prospects: short window (about five years) whose final years are World Bank forecasts. No world aggregate in Data360. |
| `wb:WB_GEP_NYGDPMKTPKDZ/IND` | GDP growth, constant (average 2010-19 prices and market exchange rates): India | 印度GDP增长率（世界银行全球经济展望） | Percent change per annum | A |  | IND | World Bank Global Economic Prospects: short window (about five years) whose final years are World Bank forecasts. No world aggregate in Data360. |
| `wb:WB_GEP_NYGDPMKTPKDZ/EMU` | GDP growth, constant (average 2010-19 prices and market exchange rates): Euro area | 欧元区GDP增长率（世界银行全球经济展望） | Percent change per annum | A |  | EMU | World Bank Global Economic Prospects: short window (about five years) whose final years are World Bank forecasts. No world aggregate in Data360. |
| `wb:WB_WDI_NY_GDP_MKTP_KD_ZG/USA` | GDP (annual % growth): United States | 美国GDP年增长率（世界发展指标） | Percent | A |  | USA | World Development Indicators history (actuals only); latest year lags one to two years. |
| `wb:WB_WDI_NY_GDP_MKTP_KD_ZG/CHN` | GDP (annual % growth): China | 中国GDP年增长率（世界发展指标） | Percent | A |  | CHN | World Development Indicators history (actuals only); latest year lags one to two years. |
| `wb:WB_WDI_NY_GDP_MKTP_KD_ZG/IND` | GDP (annual % growth): India | 印度GDP年增长率（世界发展指标） | Percent | A |  | IND | World Development Indicators history (actuals only); latest year lags one to two years. |
| `wb:WB_WDI_NY_GDP_MKTP_KD_ZG/WLD` | GDP (annual % growth): World | 世界GDP年增长率（世界发展指标） | Percent | A |  | WLD | World Development Indicators history (actuals only); latest year lags one to two years. |
| `wb:WB_WDI_SP_POP_TOTL/USA` | Population, total: United States | 美国总人口（世界发展指标） | Persons | A |  | USA | Mid-year estimates; latest year lags one to two years. |
| `wb:WB_WDI_SP_POP_TOTL/CHN` | Population, total: China | 中国总人口（世界发展指标） | Persons | A |  | CHN | Mid-year estimates; latest year lags one to two years. |
| `wb:WB_WDI_SP_POP_TOTL/IND` | Population, total: India | 印度总人口（世界发展指标） | Persons | A |  | IND | Mid-year estimates; latest year lags one to two years. |
| `wb:WB_WDI_SP_POP_TOTL/WLD` | Population, total: World | 世界总人口（世界发展指标） | Persons | A |  | WLD | Mid-year estimates; latest year lags one to two years. |
| `wb:WB_WDI_NY_GDP_PCAP_CD/USA` | GDP per capita (current US$): United States | 美国人均GDP（现价美元） | Current U.S. dollars | A |  | USA |  |
| `wb:WB_WDI_NY_GDP_PCAP_CD/CHN` | GDP per capita (current US$): China | 中国人均GDP（现价美元） | Current U.S. dollars | A |  | CHN |  |
| `wb:WB_WDI_NY_GDP_PCAP_CD/IND` | GDP per capita (current US$): India | 印度人均GDP（现价美元） | Current U.S. dollars | A |  | IND |  |
| `wb:WB_WDI_EN_GHG_CO2_MT_CE_AR5/WLD` | Carbon dioxide (CO2) emissions (total) excluding LULUCF (Mt CO2e): World | 世界二氧化碳排放总量（不含土地利用） | Mt CO2 equivalent | A |  | WLD | EDGAR-based estimates; latest year lags one to two years. |
| `wb:WB_WDI_EN_GHG_CO2_MT_CE_AR5/CHN` | Carbon dioxide (CO2) emissions (total) excluding LULUCF (Mt CO2e): China | 中国二氧化碳排放总量（不含土地利用） | Mt CO2 equivalent | A |  | CHN | EDGAR-based estimates; latest year lags one to two years. |
| `wb:WB_WDI_EN_GHG_CO2_MT_CE_AR5/USA` | Carbon dioxide (CO2) emissions (total) excluding LULUCF (Mt CO2e): United States | 美国二氧化碳排放总量（不含土地利用） | Mt CO2 equivalent | A |  | USA | EDGAR-based estimates; latest year lags one to two years. |
| `wb:WB_WDI_EN_GHG_CO2_MT_CE_AR5/IND` | Carbon dioxide (CO2) emissions (total) excluding LULUCF (Mt CO2e): India | 印度二氧化碳排放总量（不含土地利用） | Mt CO2 equivalent | A |  | IND | EDGAR-based estimates; latest year lags one to two years. |
| `wb:WB_WDI_EG_USE_ELEC_KH_PC/CHN` | Electric power consumption (kWh per capita): China | 中国人均用电量 | Kilowatt-hours per capita | A |  | CHN | Latest year lags one to two years. |
| `wb:WB_WDI_EG_USE_ELEC_KH_PC/USA` | Electric power consumption (kWh per capita): United States | 美国人均用电量 | Kilowatt-hours per capita | A |  | USA | Latest year lags one to two years. |
| `wb:WB_WDI_EG_USE_ELEC_KH_PC/IND` | Electric power consumption (kWh per capita): India | 印度人均用电量 | Kilowatt-hours per capita | A |  | IND | Latest year lags one to two years. |
| `wb:WB_WDI_FP_CPI_TOTL_ZG/CHN` | Inflation, consumer prices (annual % growth): China | 中国CPI年通胀率（世界发展指标） | Percent | A |  | CHN |  |
| `wb:WB_WDI_FP_CPI_TOTL_ZG/IND` | Inflation, consumer prices (annual % growth): India | 印度CPI年通胀率（世界发展指标） | Percent | A |  | IND |  |
| `wb:WB_WDI_NE_TRD_GNFS_ZS/CHN` | Trade (% of GDP): China | 中国贸易占GDP比重 | Percent of GDP | A |  | CHN |  |
| `wb:WB_WDI_NE_EXP_GNFS_ZS/CHN` | Exports of goods and services (% of GDP): China | 中国出口占GDP比重 | Percent of GDP | A |  | CHN |  |
| `wb:WB_WDI_SL_UEM_TOTL_ZS/CHN` | Unemployment, total (% of total labor force) (modeled ILO estimate): China | 中国失业率（国际劳工组织模型估计） | Percent of total labor force | A |  | CHN | Modeled ILO estimate; differs from China's surveyed urban unemployment rate. |

## usgov — U.S. Government Open Data (Treasury Fiscal Data, USAspending)

| Series id | Title | 中文 | Units | Freq | SA | Geo | Notes |
|---|---|---|---|---|---|---|---|
| `usgov:treasury/debt_to_penny` | Debt to the Penny: Total Public Debt Outstanding | 美国联邦公共债务总额（每日） | U.S. dollars | D |  | USA | Business-day series; includes intragovernmental holdings (use debt_held_public for market debt). |
| `usgov:treasury/debt_held_public` | Debt to the Penny: Debt Held by the Public | 美国公众持有的联邦债务（每日） | U.S. dollars | D |  | USA | Excludes intragovernmental holdings such as the Social Security trust funds. |
| `usgov:treasury/mts_deficit` | Monthly Treasury Statement: Surplus (+) or Deficit (-) (current month) | 美国联邦财政月度盈余（+）或赤字（-） | U.S. dollars | M | NSA | USA | Negative values are deficits. MTS Table 3 row selected by line_code_nbr (stable; src_line_nbr drifts between years). Strong monthly seasonality (April and September receipts); compare with the same month a year earlier… |
| `usgov:treasury/mts_receipts` | Monthly Treasury Statement: Total Receipts (current month) | 美国联邦财政月度总收入 | U.S. dollars | M | NSA | USA | MTS Table 3 row selected by line_code_nbr (stable; src_line_nbr drifts between years). Strong monthly seasonality (April and September receipts); compare with the same month a year earlier or use fiscal-year-to-date tot… |
| `usgov:treasury/mts_outlays` | Monthly Treasury Statement: Total Outlays (current month) | 美国联邦财政月度总支出 | U.S. dollars | M | NSA | USA | MTS Table 3 row selected by line_code_nbr (stable; src_line_nbr drifts between years). Strong monthly seasonality (April and September receipts); compare with the same month a year earlier or use fiscal-year-to-date tot… |
| `usgov:treasury/avg_interest_rate/Treasury Bills` | Average Interest Rates on U.S. Treasury Securities: Treasury Bills | 美国国库券平均利率 | Percent | M |  | USA | Average rate on outstanding debt (a slow-moving cost of debt), not a market yield. |
| `usgov:treasury/avg_interest_rate/Treasury Notes` | Average Interest Rates on U.S. Treasury Securities: Treasury Notes | 美国中期国债平均利率 | Percent | M |  | USA | Average rate on outstanding debt (a slow-moving cost of debt), not a market yield. |
| `usgov:treasury/avg_interest_rate/Treasury Bonds` | Average Interest Rates on U.S. Treasury Securities: Treasury Bonds | 美国长期国债平均利率 | Percent | M |  | USA | Average rate on outstanding debt (a slow-moving cost of debt), not a market yield. |
| `usgov:treasury/avg_interest_rate/Total Marketable` | Average Interest Rates on U.S. Treasury Securities: Total Marketable | 美国可交易国债平均利率 | Percent | M |  | USA | Average rate on outstanding debt (a slow-moving cost of debt), not a market yield. |
| `usgov:treasury/avg_interest_rate/Total Interest-bearing Debt` | Average Interest Rates on U.S. Treasury Securities: Total Interest-bearing Debt | 美国全部付息债务平均利率 | Percent | M |  | USA | Average rate on outstanding debt (a slow-moving cost of debt), not a market yield. |
| `usgov:treasury/fx/Euro Zone-Euro` | Treasury Reporting Rates of Exchange: Euro Zone-Euro | 美国财政部报告汇率：欧元 | Foreign currency units per U.S. dollar | Q |  | EMU | Quarter-end accounting rates, not market rates. A quarter can carry a mid-quarter amendment (later effective_date); the quarter-end rate is the earliest effective_date. |
| `usgov:treasury/fx/China-Renminbi` | Treasury Reporting Rates of Exchange: China-Renminbi | 美国财政部报告汇率：人民币 | Foreign currency units per U.S. dollar | Q |  | CHN | Quarter-end accounting rates, not market rates. A quarter can carry a mid-quarter amendment (later effective_date); the quarter-end rate is the earliest effective_date. |
| `usgov:treasury/fx/Japan-Yen` | Treasury Reporting Rates of Exchange: Japan-Yen | 美国财政部报告汇率：日元 | Foreign currency units per U.S. dollar | Q |  | JPN | Quarter-end accounting rates, not market rates. A quarter can carry a mid-quarter amendment (later effective_date); the quarter-end rate is the earliest effective_date. |
| `usgov:treasury/fx/United Kingdom-Pound` | Treasury Reporting Rates of Exchange: United Kingdom-Pound | 美国财政部报告汇率：英镑 | Foreign currency units per U.S. dollar | Q |  | GBR | Quarter-end accounting rates, not market rates. A quarter can carry a mid-quarter amendment (later effective_date); the quarter-end rate is the earliest effective_date. |
| `usgov:treasury/fx/Canada-Dollar` | Treasury Reporting Rates of Exchange: Canada-Dollar | 美国财政部报告汇率：加元 | Foreign currency units per U.S. dollar | Q |  | CAN | Quarter-end accounting rates, not market rates. A quarter can carry a mid-quarter amendment (later effective_date); the quarter-end rate is the earliest effective_date. |
| `usgov:treasury/fx/Mexico-Peso` | Treasury Reporting Rates of Exchange: Mexico-Peso | 美国财政部报告汇率：墨西哥比索 | Foreign currency units per U.S. dollar | Q |  | MEX | Quarter-end accounting rates, not market rates. A quarter can carry a mid-quarter amendment (later effective_date); the quarter-end rate is the earliest effective_date. |
| `usgov:treasury/fx/India-Rupee` | Treasury Reporting Rates of Exchange: India-Rupee | 美国财政部报告汇率：印度卢比 | Foreign currency units per U.S. dollar | Q |  | IND | Quarter-end accounting rates, not market rates. A quarter can carry a mid-quarter amendment (later effective_date); the quarter-end rate is the earliest effective_date. |
| `usgov:spending/total` | USAspending: Federal Award Spending by Fiscal Year | 美国联邦奖励支出（按财年） | U.S. dollars | A |  | USA | Award obligations (contracts, grants, loans, direct payments), not total budget outlays; periodStart is the first month of the fiscal year (FY2025 starts 2024-10). Recent years rise as agencies report late. |

## BIS dataflows (ids are `bis:<FLOW>/<KEY>`; key parts follow the dimension order)

| Flow | Version | Key dimensions (in order) | Citation topic | Title |
|---|---|---|---|---|
| WS_CBPOL | 1.0 | FREQ.REF_AREA | CBPOL | Central bank policy rates |
| WS_CREDIT_GAP | 1.0 | FREQ.BORROWERS_CTY.TC_BORROWERS.TC_LENDERS.CG_DTYPE | CREDIT_GAPS | Credit-to-GDP gaps |
| WS_TC | 2.0 | FREQ.BORROWERS_CTY.TC_BORROWERS.TC_LENDERS.VALUATION.UNIT_TYPE.TC_ADJUST | TOTAL_CREDIT | Total credit |
| WS_DSR | 1.0 | FREQ.BORROWERS_CTY.DSR_BORROWERS | DSR | Debt service ratios |
| WS_SPP | 1.0 | FREQ.REF_AREA.VALUE.UNIT_MEASURE | RPP | Selected residential property prices |
| WS_XRU | 1.0 | FREQ.REF_AREA.CURRENCY.COLLECTION | XRU | US dollar exchange rates |
| WS_EER | 1.0 | FREQ.EER_TYPE.EER_BASKET.REF_AREA | EER | Effective exchange rates |
| WS_LONG_CPI | 1.0 | FREQ.REF_AREA.UNIT_MEASURE | CPI | Consumer prices statistics |
| WS_CBTA | 1.0 | FREQ.REF_AREA.COMP_METHOD.UNIT_MEASURE.CURRENCY.TRANSFORMATION | CBTA | Central bank total assets |
| WS_GLI | 1.0 | FREQ.CURR_DENOM.BORROWERS_CTY.BORROWERS_SECTOR.LENDERS_SECTOR.L_POS_TYPE.L_INSTR.UNIT_MEASURE | GLI | Global liquidity indicators |

## IMF dataflows (ids are `imf:<FLOW>/<KEY>`)

| Flow | Agency | Key dimensions (in order) | Title |
|---|---|---|---|
| WEO | IMF.RES | COUNTRY.INDICATOR.FREQUENCY | World Economic Outlook (WEO) |
| WEO_2026_APR_VINTAGE | IMF.RES | COUNTRY.INDICATOR.FREQUENCY | World Economic Outlook (WEO) 2026 April |
| WEO_2025_OCT_VINTAGE | IMF.RES | COUNTRY.INDICATOR.FREQUENCY | World Economic Outlook (WEO) 2025 October |
| PCPS | IMF.RES | COUNTRY.INDICATOR.DATA_TRANSFORMATION.FREQUENCY | Primary Commodity Price System (PCPS) |
| CPI | IMF.STA | COUNTRY.INDEX_TYPE.COICOP_1999.TYPE_OF_TRANSFORMATION.FREQUENCY | Consumer Price Index (CPI) |

WEO vintages follow `WEO_<YYYY>_<APR|OCT>_VINTAGE` with the WEO key layout.

## usgov recipes (ids are `usgov:<recipe>[/<parameter>]`)

| Recipe | Title | Tool | Endpoint | Value field | Freq | Units | Parameter | Notes |
|---|---|---|---|---|---|---|---|---|
| `treasury/debt_to_penny` | Debt to the Penny: Total Public Debt Outstanding | treasury_query_fiscal_data | `/v2/accounting/od/debt_to_penny` | tot_pub_debt_out_amt | D | U.S. dollars |  | Business-day series; includes intragovernmental holdings (use debt_held_public for market debt). |
| `treasury/debt_held_public` | Debt to the Penny: Debt Held by the Public | treasury_query_fiscal_data | `/v2/accounting/od/debt_to_penny` | debt_held_public_amt | D | U.S. dollars |  | Excludes intragovernmental holdings such as the Social Security trust funds. |
| `treasury/mts_receipts` | Monthly Treasury Statement: Total Receipts (current month) | treasury_query_fiscal_data | `/v1/accounting/mts/mts_table_3` | current_month_rcpt_outly_amt | M | U.S. dollars |  | MTS Table 3 row selected by line_code_nbr (stable; src_line_nbr drifts between years). Strong monthly seasonality (April and September receipts); compare with the same month a year earlier or use fiscal-year-to-date tot… |
| `treasury/mts_outlays` | Monthly Treasury Statement: Total Outlays (current month) | treasury_query_fiscal_data | `/v1/accounting/mts/mts_table_3` | current_month_rcpt_outly_amt | M | U.S. dollars |  | MTS Table 3 row selected by line_code_nbr (stable; src_line_nbr drifts between years). Strong monthly seasonality (April and September receipts); compare with the same month a year earlier or use fiscal-year-to-date tot… |
| `treasury/mts_deficit` | Monthly Treasury Statement: Surplus (+) or Deficit (-) (current month) | treasury_query_fiscal_data | `/v1/accounting/mts/mts_table_3` | current_month_rcpt_outly_amt | M | U.S. dollars |  | Negative values are deficits. MTS Table 3 row selected by line_code_nbr (stable; src_line_nbr drifts between years). Strong monthly seasonality (April and September receipts); compare with the same month a year earlier… |
| `treasury/avg_interest_rate` | Average Interest Rates on U.S. Treasury Securities | treasury_query_fiscal_data | `/v2/accounting/od/avg_interest_rates` | avg_interest_rate_amt | M | Percent | <security_desc> | Average rate on outstanding debt (a slow-moving cost of debt), not a market yield. |
| `treasury/fx` | Treasury Reporting Rates of Exchange | treasury_query_fiscal_data | `/v1/accounting/od/rates_of_exchange` | exchange_rate | Q | Foreign currency units per U.S. dollar | <country_currency_desc> | Quarter-end accounting rates, not market rates. A quarter can carry a mid-quarter amendment (later effective_date); the quarter-end rate is the earliest effective_date. |
| `spending/total` | USAspending: Federal Award Spending by Fiscal Year | usa_spending_over_time | `https://api.usaspending.gov/api/v2/search/spending_over_time/` | amount | A | U.S. dollars |  | Award obligations (contracts, grants, loans, direct payments), not total budget outlays; periodStart is the first month of the fiscal year (FY2025 starts 2024-10). Recent years rise as agencies report late. |
| `sec` | SEC XBRL company concept (company facts) | sec_company_concept | `https://data.sec.gov/api/xbrl/companyconcept/` | value | A | U.S. dollars | <CIK or ticker>/<us-gaap concept> | Template, not a catalog series. Annual facts repeat across later filings (keep the latest filed per period) and include quarterly comparatives; companies switch concepts (Apple stopped tagging Revenues after FY2018). |
