# fred — FRED (Federal Reserve Bank of St. Louis)

Generated from `deerflow_bridge/data_catalog.py` by `render_catalog_files()`; do not edit by hand (regenerate with `python deerflow_bridge/data_catalog.py --write-markdown`).

83 curated series. Use for: US macro, labor, prices, policy rates and the Treasury curve, credit spreads, dollar FX, energy prices, money; free-text search over about 800,000 series. Id grammar, column legend and the other providers: [series-catalog.md](series-catalog.md).

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
| `fred:DPCERL1Q225SBEA` | Real Personal Consumption Expenditures | 美国实际个人消费支出增长率（环比折年率） | Percent Change from Preceding Period | Q | SAAR | USA | Quarter-on-quarter change at an annual rate (NIPA Table 1.1.1 line 2). |
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
| `fred:WALCL` | Assets: Total Assets: Total Assets (Less Eliminations from Consolidation): Wednesday Level | 美联储资产负债表总资产 | Millions of U.S. Dollars | W | NSA | USA | Wednesday level (a stock); weekly data are not averaged. |
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
| `fred:DFEDTARU` | Federal Funds Target Range - Upper Limit | 联邦基金目标利率区间上限 | Percent | D | NSA | USA | Step series that changes only at FOMC decisions; the lower limit is fred:DFEDTARL. |
| `fred:DFEDTARL` | Federal Funds Target Range - Lower Limit | 联邦基金目标利率区间下限 | Percent | D | NSA | USA | Step series that changes only at FOMC decisions; the upper limit is fred:DFEDTARU. |
| `fred:ECBDFR` | ECB Deposit Facility Rate for Euro Area | 欧洲央行存款便利利率 | Percent | D | NSA | EMU | The rate through which the ECB steers its policy stance; step series that changes only at Governing Council decisions. bis:WS_CBPOL/M.XM carries it from 18 Sep 2024 only (main refinancing rate before). |
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
| `fred:IPG3344S` | Industrial Production: Manufacturing: Durable Goods: Semiconductor and Other Electronic Component (NAICS = 3344) | 美国半导体及其他电子元件工业生产指数 | Index 2017=100 | M | SA | USA | Real output index for NAICS 3344 (chips and other electronic components). |
| `fred:CAPUTLG3344S` | Capacity Utilization: Manufacturing: Durable Goods: Semiconductor and Other Electronic Component (NAICS = 3344) | 美国半导体及其他电子元件产能利用率 | Percent | M | SA | USA |  |
| `fred:IPG334S` | Industrial Production: Manufacturing: Durable Goods: Computer and Electronic Product (NAICS = 334) | 美国计算机和电子产品工业生产指数 | Index 2017=100 | M | SA | USA |  |
| `fred:A34SNO` | Manufacturers' New Orders: Computers and Electronic Products | 美国计算机和电子产品新订单 | Millions of Dollars | M | SA | USA | Census M3 survey; nominal dollars. |
| `fred:A34SVS` | Manufacturers' Value of Shipments: Computers and Electronic Products | 美国计算机和电子产品出货值 | Millions of Dollars | M | SA | USA | Census M3 survey; nominal dollars for all computer and electronic products, not chips alone. |
| `fred:PCU33443344` | Producer Price Index by Industry: Semiconductor and Other Electronic Component Manufacturing | 美国半导体及其他电子元件制造业生产者价格指数 | Index Dec 1984=100 | M | NSA | USA | Quality-adjusted prices drift down over time; compare changes, not levels. |
| `fred:NASDAQSOX` | PHLX Semiconductor | 费城半导体指数 | Index | D | NSA | USA | Price index without dividends. |
| `fred:BOPGSTB` | Trade Balance: Goods and Services, Balance of Payments Basis | 美国商品和服务贸易差额 | Millions of Dollars | M | SA | USA | Negative values are deficits. |
| `fred:EXPGSC1` | Real Exports of Goods and Services | 美国实际商品和服务出口 | Billions of Chained 2017 Dollars | Q | SAAR | USA |  |
| `fred:IMPGSC1` | Real imports of goods and services | 美国实际商品和服务进口 | Billions of Chained 2017 Dollars | Q | SAAR | USA |  |
| `fred:IMPCH` | U.S. Imports of Goods by Customs Basis from China | 美国自中国商品进口额（海关口径） | Millions of Dollars | M | NSA | CHN | Census customs basis, not seasonally adjusted: compare with the same month a year earlier. |
| `fred:EXPCH` | U.S. Exports of Goods by F.A.S. Basis to Mainland China | 美国对中国大陆商品出口额 | Millions of Dollars | M | NSA | CHN | Census F.A.S. basis, not seasonally adjusted. |
| `fred:B235RC1Q027SBEA` | Federal government current tax receipts: Taxes on production and imports: Customs duties | 美国联邦关税收入（国民账户，折年率） | Billions of Dollars | Q | SAAR | USA | NIPA accrual basis at an annual rate; the monthly cash series is usgov:treasury/mts_customs_duties. |
| `fred:GFDEGDQ188S` | Federal Debt: Total Public Debt as Percent of Gross Domestic Product | 美国联邦公共债务占GDP比率 | Percent of GDP | Q | SA | USA | Gross debt including intragovernmental holdings. |
| `fred:FYFSGDA188S` | Federal Surplus or Deficit [-] as Percent of Gross Domestic Product | 美国联邦财政盈余或赤字占GDP比率 | Percent of GDP | A | NSA | USA | Fiscal-year basis; negative values are deficits. |
