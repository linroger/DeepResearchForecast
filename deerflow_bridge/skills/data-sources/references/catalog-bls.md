# bls — U.S. Bureau of Labor Statistics

Generated from `deerflow_bridge/data_catalog.py` by `render_catalog_files()`; do not edit by hand (regenerate with `python deerflow_bridge/data_catalog.py --write-markdown`).

45 curated series. Use for: authoritative US CPI/PPI detail, average prices, payrolls, JOLTS, wages, ECI, productivity, state unemployment; no free-text search, use the catalog. Id grammar, column legend and the other providers: [series-catalog.md](series-catalog.md).

| Series id | Title | 中文 | Units | Freq | SA | Geo | Notes |
|---|---|---|---|---|---|---|---|
| `bls:CUUR0000SA0` | All items in U.S. city average, all urban consumers, not seasonally adjusted | 美国CPI-U全部项目（未季调） | Index 1982-84=100 | M | NSA | USA | Index level; the published 12-month inflation rate is the yoy change of this NSA series. FRED mirror: fred:CPIAUCNS. |
| `bls:CUSR0000SA0` | All items in U.S. city average, all urban consumers, seasonally adjusted | 美国CPI-U全部项目（季调） | Index 1982-84=100 | M | SA | USA | Use for month-over-month changes; FRED mirror fred:CPIAUCSL. |
| `bls:CUUR0000SA0L1E` | All items less food and energy in U.S. city average, all urban consumers, not seasonally adjusted | 美国核心CPI（未季调） | Index 1982-84=100 | M | NSA | USA | The published 12-month core inflation rate is the yoy change of this NSA series. FRED mirror: fred:CPILFENS. |
| `bls:CUSR0000SA0L1E` | All items less food and energy in U.S. city average, all urban consumers, seasonally adjusted | 美国核心CPI（季调） | Index 1982-84=100 | M | SA | USA | FRED mirror fred:CPILFESL. |
| `bls:SUUR0000SA0` | All items in U.S. city average, all urban consumers, chained, not seasonally adjusted | 美国链式CPI-U | Index Dec 1999=100 | M | NSA | USA | Latest months are preliminary and revised for ten to twelve months. |
| `bls:CUSR0000SAH1` | Shelter in U.S. city average, all urban consumers, seasonally adjusted | 美国CPI住房分项 | Index 1982-84=100 | M | SA | USA | FRED mirror: fred:CUSR0000SAH1. |
| `bls:CUSR0000SEHA` | Rent of primary residence in U.S. city average, all urban consumers, seasonally adjusted | 美国CPI主要住所租金 | Index 1982-84=100 | M | SA | USA | FRED mirror: fred:CUSR0000SEHA. |
| `bls:CUSR0000SAF11` | Food at home in U.S. city average, all urban consumers, seasonally adjusted | 美国CPI家庭食品 | Index 1982-84=100 | M | SA | USA | FRED mirror: fred:CUSR0000SAF11. |
| `bls:CUSR0000SAM` | Medical care in U.S. city average, all urban consumers, seasonally adjusted | 美国CPI医疗保健 | Index 1982-84=100 | M | SA | USA |  |
| `bls:CUSR0000SETA02` | Used cars and trucks in U.S. city average, all urban consumers, seasonally adjusted | 美国CPI二手车 | Index 1982-84=100 | M | SA | USA | FRED mirror: fred:CUSR0000SETA02. |
| `bls:CUSR0000SASLE` | Services less energy services in U.S. city average, all urban consumers, seasonally adjusted | 美国CPI核心服务（剔除能源服务） | Index 1982-84=100 | M | SA | USA | FRED mirror: fred:CUSR0000SASLE. |
| `bls:CUUR0000SETB01` | Gasoline (all types) in U.S. city average, all urban consumers, not seasonally adjusted | 美国CPI汽油 | Index 1982-84=100 | M | NSA | USA | FRED mirror: fred:CUUR0000SETB01. |
| `bls:CUUR0000SEHF01` | Electricity in U.S. city average, all urban consumers, not seasonally adjusted | 美国CPI电力 | Index 1982-84=100 | M | NSA | USA | FRED mirror: fred:CUUR0000SEHF01. |
| `bls:APU000074714` | Gasoline, unleaded regular, per gallon/3.785 liters in U.S. city average, average price, not seasonally adjusted | 美国普通无铅汽油平均价格 | U.S. dollars per gallon | M | NSA | USA | Monthly average price; weekly retail prices are fred:GASREGW. FRED mirror: fred:APU000074714. |
| `bls:APU000072610` | Electricity per KWH in U.S. city average, average price, not seasonally adjusted | 美国居民电价（每千瓦时平均价格） | U.S. dollars per kilowatt-hour | M | NSA | USA | FRED mirror: fred:APU000072610. |
| `bls:APU0000708111` | Eggs, grade A, large, per doz. in U.S. city average, average price, not seasonally adjusted | 美国A级大鸡蛋平均价格 | U.S. dollars per dozen | M | NSA | USA | FRED mirror: fred:APU0000708111. |
| `bls:APU0000703112` | Ground beef, 100% beef, per lb. (453.6 gm) in U.S. city average, average price, not seasonally adjusted | 美国碎牛肉平均价格 | U.S. dollars per pound | M | NSA | USA | FRED mirror: fred:APU0000703112. |
| `bls:WPSFD4` | PPI Commodity data for Final demand, seasonally adjusted | 美国PPI最终需求（季调） | Index Nov 2009=100 | M | SA | USA | Corrected label: the bundled bls-query catalog mislabels this id; the official BLS title is shown here. Not 'Finished Goods'. FRED mirror: fred:PPIFIS. |
| `bls:WPUFD4` | PPI Commodity data for Final demand, not seasonally adjusted | 美国PPI最终需求（未季调） | Index Nov 2009=100 | M | NSA | USA | The published 12-month PPI change is the yoy change of this NSA series. |
| `bls:WPUFD49104` | PPI Commodity data for Final demand less foods and energy, not seasonally adjusted | 美国核心PPI（剔除食品和能源） | Index Apr 2010=100 | M | NSA | USA | Corrected label: the bundled bls-query catalog mislabels this id; the official BLS title is shown here. The catalog's WPSFD49104 'Finished Goods Less Food and Energy' is a different series. |
| `bls:WPUFD49116` | PPI Commodity data for Final demand less foods, energy, and trade services, not seasonally adjusted | 美国PPI最终需求（剔除食品、能源和贸易服务） | Index Aug 2013=100 | M | NSA | USA | Corrected label: the bundled bls-query catalog mislabels this id; the official BLS title is shown here. Not 'PPI: Final Demand' (that is WPUFD4). |
| `bls:WPU0561` | PPI Commodity data for Fuels and related products and power-Crude petroleum (domestic production), not seasonally adjusted | 美国PPI国产原油 | Index 1982=100 | M | NSA | USA |  |
| `bls:PCU221110221110` | PPI industry data for Electric power generation, not seasonally adjusted | 美国PPI发电行业 | Index Dec 2003=100 | M | NSA | USA |  |
| `bls:LNS14000000` | (Seas) Unemployment Rate | 美国失业率（16岁及以上，季调） | Percent | M | SA | USA | Household survey (CPS); FRED mirror fred:UNRATE. October 2025 missing (2025 federal shutdown). |
| `bls:LNU04000000` | (Unadj) Unemployment Rate | 美国失业率（未季调） | Percent | M | NSA | USA | FRED mirror: fred:UNRATENSA. |
| `bls:LNS11300000` | (Seas) Labor Force Participation Rate | 美国劳动参与率 | Percent | M | SA | USA | FRED mirror: fred:CIVPART. |
| `bls:LNS12300060` | (Seas) Employment-Population Ratio - 25-54 yrs. | 美国25-54岁就业人口比 | Percent | M | SA | USA | FRED mirror: fred:LNS12300060. |
| `bls:CES0000000001` | All employees, thousands, total nonfarm, seasonally adjusted | 美国非农就业人数 | Thousands of persons | M | SA | USA | Establishment survey; FRED mirror fred:PAYEMS. Latest two months are preliminary. |
| `bls:CES3000000001` | All employees, thousands, manufacturing, seasonally adjusted | 美国制造业就业人数 | Thousands of persons | M | SA | USA | FRED mirror: fred:MANEMP. |
| `bls:CES0500000003` | Average hourly earnings of all employees, total private, seasonally adjusted | 美国私营部门平均时薪 | U.S. dollars per hour | M | SA | USA | FRED mirror: fred:CES0500000003. |
| `bls:CES0500000011` | Average weekly earnings of all employees, total private, seasonally adjusted | 美国私营部门平均周薪 | U.S. dollars per week | M | SA | USA | FRED mirror: fred:CES0500000011. |
| `bls:CES0500000002` | Average weekly hours of all employees, total private, seasonally adjusted | 美国私营部门平均每周工时 | Hours | M | SA | USA | FRED mirror: fred:AWHAETP. |
| `bls:JTS000000000000000JOL` | Job openings: total nonfarm, all size classes, level in thousands, seasonally adjusted | 美国职位空缺数（JOLTS） | Thousands | M | SA | USA | Published about five weeks after the reference month; FRED mirror fred:JTSJOL. |
| `bls:JTS000000000000000QUR` | Quits rate: total nonfarm, all size classes, seasonally adjusted | 美国离职率（主动辞职） | Percent | M | SA | USA | FRED mirror: fred:JTSQUR. |
| `bls:JTS000000000000000HIR` | Hires rate: total nonfarm, all size classes, seasonally adjusted | 美国招聘率 | Percent | M | SA | USA | FRED mirror: fred:JTSHIR. |
| `bls:JTS000000000000000LDR` | Layoffs and discharges rate: total nonfarm, all size classes, seasonally adjusted | 美国裁员率 | Percent | M | SA | USA | FRED mirror: fred:JTSLDR. |
| `bls:LASST060000000000003` | Unemployment rate: California, statewide, seasonally adjusted | 加州失业率 | Percent | M | SA | USA | LAUS state estimate; revised annually. |
| `bls:LASST480000000000003` | Unemployment rate: Texas, statewide, seasonally adjusted | 得克萨斯州失业率 | Percent | M | SA | USA | LAUS state estimate; revised annually. |
| `bls:LASST360000000000003` | Unemployment rate: New York, statewide, seasonally adjusted | 纽约州失业率 | Percent | M | SA | USA | LAUS state estimate; revised annually. |
| `bls:CIU1010000000000A` | Total compensation for all civilian workers, 12-month percent change, current dollars | 美国雇佣成本指数（总薪酬，同比） | Percent change over 12 months | Q | NSA | USA | Id suffix encodes the measure: A = 12-month percent change, I = index, Q = 3-month percent change. |
| `bls:CIU1010000000000I` | Total compensation for all civilian workers, current dollar index | 美国雇佣成本指数（总薪酬，指数） | Index Dec 2005=100 | Q | NSA | USA |  |
| `bls:PRS85006092` | Nonfarm Business: Labor productivity (output per hour), % change from previous quarter | 美国非农企业劳动生产率（环比折年率） | Percent change from previous quarter at annual rate | Q | SA | USA |  |
| `bls:PRS85006112` | Nonfarm Business: Unit labor costs, % change from previous quarter | 美国非农企业单位劳动力成本（环比折年率） | Percent change from previous quarter at annual rate | Q | SA | USA |  |
| `bls:EIUIR` | Monthly import price index for BEA End Use, All commodities, not seasonally adjusted | 美国进口价格指数 | Index 2000=100 | M | NSA | USA |  |
| `bls:EIUIQ` | Monthly export price index for BEA End Use, All commodities, not seasonally adjusted | 美国出口价格指数 | Index 2000=100 | M | NSA | USA |  |
