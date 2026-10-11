/**
 * NIH RePORTER SDK — typed API client for NIH research project and publication search.
 *
 * Standalone — no MCP server required. Usage:
 *
 *   import { searchProjects, searchPublications } from "us-gov-open-data-mcp/sdk/nih";
 *
 *   const projects = await searchProjects({ text: "Alzheimer", fiscal_years: [2024] });
 *   const pubs = await searchPublications({ core_project_nums: ["R01AG060942"] });
 *
 * No API key required.
 * Docs: https://api.reporter.nih.gov/
 */

import { createClient } from "../../shared/client.js";

// ─── Client ──────────────────────────────────────────────────────────

const api = createClient({
  baseUrl: "https://api.reporter.nih.gov/v2",
  name: "nih",
  rateLimit: { perSecond: 1, burst: 3 }, // NIH requests max 1 req/sec
  cacheTtlMs: 60 * 60 * 1000, // 1 hour
});

// ─── Types ───────────────────────────────────────────────────────────

/** Nih Project Search Response. */
export interface NihProjectSearchResponse {
  meta: {
    search_id?: string;
    total?: number;
    offset?: number;
    limit?: number;
    sort_field?: string;
    sort_order?: string;
    sorted_by_relevance?: boolean;
    properties?: Record<string, unknown>;
  };
  results: NihProject[];
}

/** Nih Project. */
export interface NihProject {
  appl_id?: number;
  subproject_id?: string | null;
  fiscal_year?: number;
  project_num?: string;
  project_serial_num?: string;
  organization?: {
    org_name?: string;
    city?: string;
    state?: string;
    country?: string;
    org_city?: string;
    org_state?: string;
    org_country?: string;
    dept_type?: string;
    fips?: string;
    org_duns?: string[];
    org_ueis?: string[];
    org_zipcode?: string;
    external_org_id?: number;
    org_type?: string;
    congressional_district?: string;
  };
  award_type?: string;
  activity_code?: string;
  award_amount?: number;
  is_active?: boolean;
  project_num_split?: {
    appl_type_code?: string;
    activity_code?: string;
    ic_code?: string;
    serial_num?: string;
    support_year?: string;
    suffix_code?: string;
    full_support_year?: string;
  };
  principal_investigators?: Array<{
    profile_id?: number;
    first_name?: string;
    middle_name?: string;
    last_name?: string;
    full_name?: string;
    is_contact_pi?: boolean;
    title?: string;
  }>;
  contact_pi_name?: string;
  program_officers?: Array<{
    first_name?: string;
    last_name?: string;
    full_name?: string;
  }>;
  agency_ic_admin?: {
    code?: string;
    abbreviation?: string;
    name?: string;
  };
  agency_ic_fundings?: Array<{
    code?: string;
    abbreviation?: string;
    name?: string;
    total_cost?: number;
  }>;
  cong_dist?: string;
  spending_categories?: Array<{
    name?: string;
    id?: number;
  }>;
  project_start_date?: string;
  project_end_date?: string;
  award_notice_date?: string;
  is_new?: boolean;
  mechanism_code_dc?: string;
  core_project_num?: string;
  terms?: string;
  pref_terms?: string;
  abstract_text?: string;
  project_title?: string;
  phr_text?: string;
  spending_categories_desc?: string;
  agency_code?: string;
  covid_response?: string[];
  arra_funded?: string;
  budget_start?: string;
  budget_end?: string;
  cfda_code?: string;
  funding_mechanism?: string;
  direct_cost_amt?: number;
  indirect_cost_amt?: number;
  project_detail_url?: string;
  date_added?: string;
}

/** Nih Publication Search Response. */
export interface NihPublicationSearchResponse {
  meta: {
    search_id?: string;
    total?: number;
    offset?: number;
    limit?: number;
    sort_field?: string;
    sort_order?: string;
    properties?: Record<string, unknown>;
  };
  results: NihPublication[];
}

/** Nih Publication. */
export interface NihPublication {
  coreproject?: string;
  pmid?: number;
  applid?: number;
}

// ─── Reference Data ──────────────────────────────────────────────────

/** NIH Institute/Center codes. */
export const NIH_AGENCIES = {
  NCI: "National Cancer Institute",
  NHLBI: "National Heart, Lung, and Blood Institute",
  NIDDK: "National Institute of Diabetes and Digestive and Kidney Diseases",
  NINDS: "National Institute of Neurological Disorders and Stroke",
  NIA: "National Institute on Aging",
  NIAID: "National Institute of Allergy and Infectious Diseases",
  NIGMS: "National Institute of General Medical Sciences",
  NIMH: "National Institute of Mental Health",
  NIDA: "National Institute on Drug Abuse",
  NICHD: "Eunice Kennedy Shriver National Institute of Child Health and Human Development",
  NEI: "National Eye Institute",
  NIEHS: "National Institute of Environmental Health Sciences",
  NIDCR: "National Institute of Dental and Craniofacial Research",
  NIAMS: "National Institute of Arthritis and Musculoskeletal and Skin Diseases",
  NIDCD: "National Institute on Deafness and Other Communication Disorders",
  NIBIB: "National Institute of Biomedical Imaging and Bioengineering",
  NIMHD: "National Institute on Minority Health and Health Disparities",
  NCATS: "National Center for Advancing Translational Sciences",
  NCCIH: "National Center for Complementary and Integrative Health",
  NLM: "National Library of Medicine",
  FIC: "Fogarty International Center",
  CIT: "Center for Information Technology",
  CSR: "Center for Scientific Review",
  OD: "NIH Office of the Director",
  NIAAA: "National Institute on Alcohol Abuse and Alcoholism",
  NHGRI: "National Human Genome Research Institute",
  NINR: "National Institute of Nursing Research",
  AHRQ: "Agency for Healthcare Research and Quality",
  CDC: "Centers for Disease Control and Prevention",
  FDA: "Food and Drug Administration",
  SAMHSA: "Substance Abuse and Mental Health Services Administration",
  VA: "Department of Veterans Affairs",
} as const;

/** NIH Spending Categories (RCDC) — common ones. */
export const SPENDING_CATEGORIES = {
  2: "Aging",
  7: "Alzheimer's Disease",
  9: "Arthritis",
  10: "Asthma",
  13: "Biodefense",
  20: "Brain Disorders",
  27: "Cancer",
  30: "Cardiovascular",
  35: "Clinical Research",
  38: "COVID-19/SARS-CoV-2",
  40: "Depression",
  41: "Diabetes",
  47: "Drug Abuse",
  55: "Genetics",
  57: "Global Health",
  60: "HIV/AIDS",
  70: "Immunization",
  74: "Infectious Diseases",
  78: "Kidney Disease",
  82: "Lung",
  85: "Mental Health",
  88: "Minority Health",
  92: "Obesity",
  93: "Opioids",
  95: "Orphan Drug",
  100: "Pain Research",
  105: "Precision Medicine",
  109: "Rare Diseases",
  115: "Stem Cell Research",
  118: "Stroke",
  120: "Substance Abuse",
  123: "Tobacco",
  126: "Vaccine Related",
  128: "Women's Health",
} as const;

/** Common activity codes (grant types). */
export const ACTIVITY_CODES = {
  R01: "Research Project Grant (most common independent investigator grant)",
  R21: "Exploratory/Developmental Research Grant (smaller, high-risk)",
  R43: "SBIR Phase I (Small Business Innovation Research)",
  R44: "SBIR Phase II",
  P01: "Research Program Project Grant (multi-investigator)",
  P30: "Center Core Grant",
  P50: "Specialized Center",
  U01: "Research Project Cooperative Agreement",
  U54: "Specialized Center Cooperative Agreement",
  T32: "Institutional NRSA Training Grant",
  F31: "Pre-doctoral Fellowship",
  F32: "Post-doctoral Fellowship",
  K01: "Mentored Research Scientist Career Development Award",
  K08: "Mentored Clinical Scientist Career Development Award",
  K23: "Mentored Patient-Oriented Research Career Development Award",
  K99: "Pathway to Independence Award (Phase I)",
  R00: "Pathway to Independence Award (Phase II)",
  DP2: "NIH Director's New Innovator Award",
  DP5: "NIH Director's Early Independence Award",
  ZIA: "NIH Intramural Research Project",
} as const;

/** Funding mechanism codes. */
export const FUNDING_MECHANISMS = {
  RG: "Research Grants",
  PC: "Research Centers",
  CT: "Clinical Trial or Study Cooperative Agreement",
  TN: "Research Training (Individual and Institutional)",
  CR: "Research Career Programs",
  SB: "Small Business Awards (SBIR/STTR)",
  OT: "Other Transactions",
} as const;

// ─── Public API ──────────────────────────────────────────────────────

/**
 * Search NIH-funded research projects.
 *
 * Examples:
 *   const cancer = await searchProjects({ text: "breast cancer", fiscal_years: [2024] });
 *   const byAgency = await searchProjects({ agencies: ["NCI"], limit: 20 });
 *   const byPI = await searchProjects({ pi_names: [{ any_name: "Fauci" }] });
 *   const byOrg = await searchProjects({ org_names: ["JOHNS HOPKINS UNIVERSITY"] });
 *   const bySpending = await searchProjects({ spending_categories: [27], fiscal_years: [2024] });
 */
export async function searchProjects(opts: {
  text?: string;
  search_field?: string;
  fiscal_years?: number[];
  agencies?: string[];
  pi_names?: Array<{ first_name?: string; last_name?: string; any_name?: string }>;
  po_names?: Array<{ first_name?: string; last_name?: string; any_name?: string }>;
  org_names?: string[];
  org_states?: string[];
  org_cities?: string[];
  org_countries?: string[];
  spending_categories?: number[];
  spending_categories_match_all?: boolean;
  activity_codes?: string[];
  funding_mechanism?: string[];
  award_types?: string[];
  award_amount_min?: number;
  award_amount_max?: number;
  project_nums?: string[];
  appl_ids?: number[];
  include_active_projects?: boolean;
  exclude_subprojects?: boolean;
  covid_response?: string[];
  project_start_from?: string;
  project_start_to?: string;
  project_end_from?: string;
  project_end_to?: string;
  newly_added_only?: boolean;
  include_fields?: string[];
  exclude_fields?: string[];
  offset?: number;
  limit?: number;
  sort_field?: string;
  sort_order?: "asc" | "desc";
}): Promise<NihProjectSearchResponse> {
  const criteria: Record<string, unknown> = {};

  if (opts.text) {
    criteria.advanced_text_search = {
      operator: "and",
      search_field: opts.search_field || "projecttitle,terms,abstracttext",
      search_text: opts.text,
    };
  }
  if (opts.fiscal_years?.length) criteria.fiscal_years = opts.fiscal_years;
  if (opts.agencies?.length) criteria.agencies = opts.agencies;
  if (opts.pi_names?.length) criteria.pi_names = opts.pi_names;
  if (opts.po_names?.length) criteria.po_names = opts.po_names;
  if (opts.org_names?.length) criteria.org_names = opts.org_names;
  if (opts.org_states?.length) criteria.org_states = opts.org_states;
  if (opts.org_cities?.length) criteria.org_cities = opts.org_cities;
  if (opts.org_countries?.length) criteria.org_countries = opts.org_countries;
  if (opts.spending_categories?.length) {
    criteria.spending_categories = {
      values: opts.spending_categories,
      match_all: opts.spending_categories_match_all ? "true" : "false",
    };
  }
  if (opts.activity_codes?.length) criteria.activity_codes = opts.activity_codes;
  if (opts.funding_mechanism?.length) criteria.funding_mechanism = opts.funding_mechanism;
  if (opts.award_types?.length) criteria.award_types = opts.award_types;
  if (opts.award_amount_min !== undefined || opts.award_amount_max !== undefined) {
    criteria.award_amount_range = {
      min_amount: opts.award_amount_min ?? 0,
      max_amount: opts.award_amount_max ?? 999999999,
    };
  }
  if (opts.project_nums?.length) criteria.project_nums = opts.project_nums;
  if (opts.appl_ids?.length) criteria.appl_ids = opts.appl_ids;
  if (opts.include_active_projects !== undefined) criteria.include_active_projects = opts.include_active_projects;
  if (opts.exclude_subprojects !== undefined) criteria.exclude_subprojects = opts.exclude_subprojects;
  if (opts.covid_response?.length) criteria.covid_response = opts.covid_response;
  if (opts.newly_added_only) criteria.newly_added_projects_only = true;
  if (opts.project_start_from || opts.project_start_to) {
    criteria.project_start_date = {
      from_date: opts.project_start_from ?? "",
      to_date: opts.project_start_to ?? "",
    };
  }
  if (opts.project_end_from || opts.project_end_to) {
    criteria.project_end_date = {
      from_date: opts.project_end_from ?? "",
      to_date: opts.project_end_to ?? "",
    };
  }

  const body: Record<string, unknown> = { criteria };
  if (opts.offset !== undefined) body.offset = opts.offset;
  body.limit = opts.limit ?? 10;
  if (opts.sort_field) body.sort_field = opts.sort_field;
  if (opts.sort_order) body.sort_order = opts.sort_order;
  if (opts.include_fields?.length) body.include_fields = opts.include_fields;
  if (opts.exclude_fields?.length) body.exclude_fields = opts.exclude_fields;

  return api.post<NihProjectSearchResponse>("/projects/search", body);
}

/**
 * Search for publications linked to NIH-funded projects.
 *
 * Examples:
 *   const pubs = await searchPublications({ core_project_nums: ["R01AG060942"] });
 *   const byPmid = await searchPublications({ pmids: [33298401, 33105091] });
 */
export async function searchPublications(opts: {
  pmids?: number[];
  appl_ids?: number[];
  core_project_nums?: string[];
  offset?: number;
  limit?: number;
  sort_field?: string;
  sort_order?: "asc" | "desc";
}): Promise<NihPublicationSearchResponse> {
  const criteria: Record<string, unknown> = {};

  if (opts.pmids?.length) criteria.pmids = opts.pmids;
  if (opts.appl_ids?.length) criteria.appl_ids = opts.appl_ids;
  if (opts.core_project_nums?.length) criteria.core_project_nums = opts.core_project_nums;

  const body: Record<string, unknown> = { criteria };
  if (opts.offset !== undefined) body.offset = opts.offset;
  body.limit = opts.limit ?? 10;
  if (opts.sort_field) body.sort_field = opts.sort_field;
  if (opts.sort_order) body.sort_order = opts.sort_order;

  return api.post<NihPublicationSearchResponse>("/publications/search", body);
}

/**
 * Get NIH funding for a disease area across fiscal years.
 * Uses both RCDC spending categories AND the mapped agency (when available)
 * for more accurate counts, since RCDC tags aren't always applied at project level.
 *
 * Example:
 *   const cancer = await getSpendingByCategory(27, [2020, 2021, 2022, 2023, 2024]);
 */
export async function getSpendingByCategory(
  categoryId: number,
  fiscalYears: number[],
): Promise<{ category: string; years: Record<number, { projects: number; totalFunding: number; method: string }> }> {
  const categoryName = (SPENDING_CATEGORIES as Record<number, string>)[categoryId] ?? `Category ${categoryId}`;

  // Map common RCDC categories to their primary NIH institute for better counts
  const categoryToAgency: Record<number, string> = {
    27: "NCI",     // Cancer
    7: "NIA",      // Alzheimer's (NIA is primary funder)
    41: "NIDDK",   // Diabetes
    60: "NIAID",   // HIV/AIDS (NIAID is primary funder)
    85: "NIMH",    // Mental Health
    93: "NIDA",    // Opioids (NIDA is primary funder)
    30: "NHLBI",   // Cardiovascular
    118: "NINDS",  // Stroke
    78: "NIDDK",   // Kidney Disease
    82: "NHLBI",   // Lung
    47: "NIDA",    // Drug Abuse
    120: "NIDA",   // Substance Abuse
  };

  const years: Record<number, { projects: number; totalFunding: number; method: string }> = {};
  const agencyCode = categoryToAgency[categoryId];

  for (const fy of fiscalYears) {
    // Try RCDC category first
    const rcdcRes = await searchProjects({
      spending_categories: [categoryId],
      fiscal_years: [fy],
      limit: 50,
      exclude_subprojects: true,
      sort_field: "award_amount",
      sort_order: "desc",
    });
    const rcdcCount = rcdcRes.meta.total ?? 0;

    // Sum funding from returned projects as an estimate
    let rcdcFunding = 0;
    for (const p of rcdcRes.results ?? []) {
      rcdcFunding += p.award_amount ?? 0;
    }

    // If there's a mapped agency, also get that count
    if (agencyCode && rcdcCount < 500) {
      const agencyRes = await searchProjects({
        agencies: [agencyCode],
        fiscal_years: [fy],
        limit: 50,
        exclude_subprojects: true,
        sort_field: "award_amount",
        sort_order: "desc",
      });
      const agencyCount = agencyRes.meta.total ?? 0;

      let agencyFunding = 0;
      for (const p of agencyRes.results ?? []) {
        agencyFunding += p.award_amount ?? 0;
      }

      // Use whichever has more projects (agency count is usually more complete)
      if (agencyCount > rcdcCount) {
        years[fy] = {
          projects: agencyCount,
          totalFunding: agencyFunding,
          method: `${agencyCode} agency (${rcdcCount} via RCDC tag)`,
        };
        continue;
      }
    }

    years[fy] = {
      projects: rcdcCount,
      totalFunding: rcdcFunding,
      method: "RCDC category tag",
    };
  }

  return { category: categoryName, years };
}

/**
 * Get project count by NIH agency/institute for a fiscal year.
 *
 * Example:
 *   const breakdown = await getProjectsByAgency(2024);
 */
export async function getProjectsByAgency(
  fiscalYear: number,
  agencies?: string[],
): Promise<Array<{ agency: string; name: string; projectCount: number }>> {
  const agencyList = agencies ?? Object.keys(NIH_AGENCIES).slice(0, 25); // Top 25 by default
  const results: Array<{ agency: string; name: string; projectCount: number }> = [];

  for (const code of agencyList) {
    const res = await searchProjects({
      agencies: [code],
      fiscal_years: [fiscalYear],
      limit: 1,
      exclude_subprojects: true,
    });
    results.push({
      agency: code,
      name: (NIH_AGENCIES as Record<string, string>)[code] ?? code,
      projectCount: res.meta.total ?? 0,
    });
  }

  results.sort((a, b) => b.projectCount - a.projectCount);
  return results;
}

/** Clear the cache. */
export function clearCache(): void {
  api.clearCache();
}
