# bis — Bank for International Settlements (BIS)

Generated from `deerflow_bridge/data_catalog.py` by `render_catalog_files()`; do not edit by hand (regenerate with `python deerflow_bridge/data_catalog.py --write-markdown`).

50 curated series. Use for: cross-country central bank policy rates, credit-to-GDP gaps, total credit, debt service ratios, property prices, USD and effective exchange rates, central bank assets. Id grammar, column legend and the other providers: [series-catalog.md](series-catalog.md).

| Series id | Title | 中文 | Units | Freq | SA | Geo | Notes |
|---|---|---|---|---|---|---|---|
| `bis:WS_CBPOL/M.US` | Central bank policy rates - United States - Monthly - End of period | 美国央行政策利率 | Per cent per year | M |  | USA | For the United States BIS reports the midpoint of the federal funds target range; fred:DFEDTARU is the upper limit. |
| `bis:WS_CBPOL/M.XM` | Central bank policy rates - Euro area - Monthly - End of period | 欧元区央行政策利率 | Per cent per year | M |  | EMU | From 18 Sep 2024 BIS reports the ECB deposit facility rate (daily: fred:ECBDFR); before that, the main refinancing operations rate. |
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
