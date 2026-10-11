/**
 * BEA types, interfaces, and reference data constants.
 *
 * Separated from sdk.ts for clarity. Re-exported via index.ts barrel.
 */

// ─── API Response Types ──────────────────────────────────────────────────

/** Individual data row from any BEA dataset. Fields vary by dataset. */
export interface BeaDataRow {
  LineDescription?: string;
  SeriesCode?: string;
  TimePeriod?: string;
  DataValue?: string;
  GeoName?: string;
  GeoFips?: string;
  InduDesc?: string;
  IndustrYDescription?: string;  // BEA's actual field name (capital Y) for GDPbyIndustry
  Industry?: string;
  Year?: string;
  Quarter?: string;
  [key: string]: unknown;
}

/** Raw BEA API JSON envelope — the single type assertion target for all responses.
 *  Used internally by SDK helpers to avoid scattered `as any` casts. */
export interface BeaRawResponse {
  BEAAPI?: {
    Request?: unknown;
    Results?: Record<string, unknown>;
    Error?: {
      APIErrorCode?: string;
      APIErrorDescription?: string;
      ErrorDetail?: unknown;
    };
  };
}

// ─── SDK Result Types ────────────────────────────────────────────────

/** Result from NIPA / NIUnderlyingDetail / FixedAssets (table-based national data). */
export interface BeaNationalGdpResult {
  table: string;
  frequency: string;
  dataRows: number;
  series: { description: string; observations: { period: string; value: number | null }[] }[];
}

/** Result from Regional dataset when requesting all states. */
export interface BeaStateGdpResult {
  year?: string;
  unit: string;
  states?: { name: string; gdpMillions: number }[];
  geoFips?: string;
  series?: { name: string; observations: { year: string; gdpMillions: number | null }[] }[];
}

/** Result from Regional dataset for personal income tables. */
export interface BeaPersonalIncomeResult {
  table: string;
  year: string;
  unit: string;
  states: { name: string; value: number }[];
}

/** Result from GDPbyIndustry / UnderlyingGDPbyIndustry datasets. */
export interface BeaIndustryGdpResult {
  tableId: string;
  industries: { industry: string; observations: { period: string; value: number | null }[] }[];
}

// ─── Meta-data Discovery Types ───────────────────────────────────────

/** BEA Dataset info from GetDatasetList. */
export interface BeaDatasetInfo {
  DatasetName: string;
  DatasetDescription: string;
}

/** BEA Parameter info from GetParameterList. */
export interface BeaParameterInfo {
  ParameterName: string;
  ParameterDataType: string;
  ParameterDescription: string;
  ParameterIsRequiredFlag: string;
  ParameterDefaultValue?: string;
  MultipleAcceptedFlag: string;
  AllValue?: string;
}

/** BEA Parameter value from GetParameterValues / GetParameterValuesFiltered. */
export interface BeaParamValue {
  Key: string;
  Desc: string;
}

// ─── Dataset-specific Result Types ───────────────────────────────────

/** Generic BEA result for datasets without specialized output (MNE, InputOutput). */
export interface BeaGenericResult {
  dataset: string;
  params: Record<string, string>;
  dataRows: number;
  data: BeaDataRow[];
  notes?: string[];
}

/** BEA ITA (International Transactions) result. */
export interface BeaItaResult {
  dataRows: number;
  series: {
    indicator: string;
    area: string;
    description: string;
    observations: { period: string; value: number | null }[];
  }[];
}

/** BEA IIP (International Investment Position) result. */
export interface BeaIipResult {
  dataRows: number;
  series: {
    investmentType: string;
    component: string;
    description: string;
    observations: { period: string; value: number | null }[];
  }[];
}

/** BEA IntlServTrade (International Services Trade) result. */
export interface BeaIntlServTradeResult {
  dataRows: number;
  series: {
    service: string;
    direction: string;
    area: string;
    description: string;
    observations: { period: string; value: number | null }[];
  }[];
}

// ─── Reference Data ──────────────────────────────────────────────────

/** NIPA table codes and descriptions. Use these as the `tableName` parameter in getNationalGdp. */
export const nipaTables = {
  // GDP and components
  T10101: "Real GDP percent change from preceding period",
  T10102: "Contributions to percent change in real GDP",
  T10103: "Real GDP quantity indexes",
  T10104: "Nominal GDP percent change from preceding period",
  T10105: "Nominal GDP",
  T10106: "Real GDP (chained dollars)",
  T10107: "GDP implicit price deflators",
  T10108: "GDP chain-type price indexes",
  T10109: "GDP price indexes: percent change",
  T10111: "Real GDP percent change (additional detail)",
  // Personal income and outlays
  T20100: "Personal income and its disposition",
  T20200A: "Personal consumption expenditures by major type (current)",
  T20301: "PCE: durable goods",
  T20600: "Personal income and its disposition (monthly)",
  T20900: "Personal income and its disposition (percent change)",
  // Government
  T30100: "Government current receipts and expenditures",
  T30200: "Federal government current receipts and expenditures",
  T30300: "State and local government current receipts and expenditures",
  T30500: "Government consumption expenditures and gross investment",
  // Foreign transactions
  T40100: "Foreign transactions in the NIPAs",
  T40201: "Exports of goods and services",
  T40202: "Imports of goods and services",
  // Saving and investment
  T50100: "Saving and investment by sector",
  T50203: "Gross private fixed investment in equipment",
  // National income and corporate profits
  T60100B: "National income by type of income",
  T60200A: "Compensation of employees",
  T70100: "Corporate profits with IVA and CCAdj",
  T72100: "Motor vehicle output",
} as const;

/** GDP by industry table IDs. Use these as the `tableId` parameter in getGdpByIndustry. */
export const gdpIndustryTables = {
  1: "Value added by industry (current dollars)",
  5: "Contributions to percent change in real GDP by industry",
  6: "Value added as percentage of GDP by industry",
  7: "Gross output by industry (current dollars)",
  8: "Intermediate inputs by industry (current dollars)",
  12: "Gross operating surplus by industry",
  13: "Compensation of employees by industry",
  15: "Employment (full-time and part-time) by industry",
  25: "Real value added by industry (chained dollars)",
  26: "Real gross output by industry (chained dollars)",
} as const;

/** BEA Regional table codes. Use these as the `tableName` parameter in getGdpByState and getPersonalIncome. */
export const regionalTables = {
  // State annual GDP
  SAGDP1: "State annual GDP summary",
  SAGDP2: "GDP by state (by industry)",
  SAGDP3: "Taxes on production and imports less subsidies",
  SAGDP4: "Compensation of employees by industry",
  SAGDP5: "Subsidies by state",
  SAGDP6: "Taxes on production and imports by state",
  SAGDP7: "Gross operating surplus by state",
  SAGDP8: "Chain-type quantity indexes for real GDP by state (2017=100)",
  SAGDP9: "Real GDP by state",
  SAGDP11: "Contributions to percent change in real GDP by state",
  // State quarterly GDP
  SQGDP1: "State quarterly GDP summary",
  SQGDP2: "GDP by state (quarterly by industry)",
  SQGDP8: "Chain-type quantity indexes for real GDP (quarterly)",
  SQGDP9: "Real GDP by state (quarterly)",
  SQGDP11: "Contributions to percent change in real GDP (quarterly)",
  // State annual personal income
  SAINC1: "Personal income, population, per capita income",
  SAINC4: "Personal income by major component",
  SAINC5N: "Personal income by NAICS industry",
  SAINC6N: "Compensation of employees by NAICS industry",
  SAINC7N: "Wages and salaries by NAICS industry",
  SAINC11: "Contributions of earnings to percent change in personal income",
  SAINC12: "Personal income change by component",
  SAINC30: "Economic profile",
  SAINC35: "Personal current transfer receipts",
  SAINC40: "Property income",
  SAINC50: "Personal current taxes",
  SAINC51: "Disposable personal income summary",
  SAINC91: "Gross flow of earnings",
  // State quarterly personal income
  SQINC1: "State quarterly personal income summary",
  SQINC4: "Personal income by major component (quarterly)",
  SQINC5N: "Personal income by NAICS industry (quarterly)",
  SQINC35: "Personal current transfer receipts (quarterly)",
  // County GDP and income
  CAGDP1: "County GDP summary",
  CAGDP2: "GDP by county (by industry)",
  CAGDP9: "Real GDP by county",
  CAGDP11: "Contributions to percent change in real GDP by county",
  CAINC1: "County personal income summary",
  CAINC4: "Personal income by major component (county)",
  CAINC5N: "Personal income by NAICS industry (county)",
  CAINC30: "Economic profile (county)",
  CAINC91: "Gross flow of earnings (county)",
  // Regional price parities and consumer spending
  SARPP: "Regional price parities by state",
  MARPP: "Regional price parities by MSA",
  PARPP: "Regional price parities by metro/nonmetro portion",
  SAPCE1: "PCE by major type of product",
  SAPCE2: "Per capita PCE by major type of product",
  SAPCE3: "PCE by state by type of product",
  SAPCE4: "PCE by state by function",
  // Summary
  SASUMMARY: "State annual income and product summary",
} as const;

/** BEA datasets and their descriptions. */
export const beaDatasets = {
  NIPA: "National Income and Product Accounts (GDP, income, spending)",
  NIUnderlyingDetail: "NIPA underlying detail (more granular, lower quality)",
  FixedAssets: "Fixed assets (net stock, depreciation, investment)",
  MNE: "Multinational Enterprises (direct investment, foreign affiliates)",
  GDPbyIndustry: "GDP by industry (value added, gross output, inputs)",
  Regional: "Regional data (state/county/MSA income, GDP, employment)",
  ITA: "International Transactions Accounts (balance of payments)",
  IIP: "International Investment Position (assets, liabilities)",
  InputOutput: "Input-Output statistics (make/use/requirements tables)",
  UnderlyingGDPbyIndustry: "Underlying GDP by industry (additional detail, lower quality)",
  IntlServTrade: "International Services Trade",
} as const;
