/**
 * ClinicalTrials.gov SDK — typed API client for the v2 REST API.
 *
 * Standalone — no MCP server required. Usage:
 *
 *   import { searchTrials, getTrialDetail, getFieldValueStats } from "us-gov-open-data-mcp/sdk/clinical-trials";
 *
 *   const trials = await searchTrials({ condition: "lung cancer", status: "RECRUITING" });
 *   const detail = await getTrialDetail("NCT06000000");
 *   const phases = await getFieldValueStats({ fields: ["Phase"] });
 *
 * No API key required.
 * Base URL: https://clinicaltrials.gov/api/v2
 * Docs: https://clinicaltrials.gov/data-api/api
 */

import { createClient, qp } from "../../shared/client.js";
import type {
  Study,
  PagedStudies,
  FieldNode,
  SearchDocument,
  EnumInfo,
  FieldValueStats,
  ListSizeStats,
  SizeStats,
  VersionInfo,
} from "./types.js";
import {
  AGG_PHASE_CODES,
  AGG_STUDY_TYPE_CODES,
} from "./types.js";

// Re-export types and constants for SDK consumers
export type {
  Study,
  PagedStudies,
  FieldNode,
  SearchDocument,
  EnumInfo,
  FieldValueStats,
  ListSizeStats,
  SizeStats,
  VersionInfo,
} from "./types.js";
export {
  TRIAL_STATUSES,
  TRIAL_PHASES,
  STUDY_TYPES,
  INTERVENTION_TYPES,
  AGENCY_CLASSES,
  STANDARD_AGES,
  SEX_VALUES,
  FIELD_STATS_TYPES,
  AGG_PHASE_CODES,
  AGG_STUDY_TYPE_CODES,
  SEARCH_DEFAULT_FIELDS,
} from "./types.js";

// ─── Client ──────────────────────────────────────────────────────────

const api = createClient({
  baseUrl: "https://clinicaltrials.gov/api/v2",
  name: "clinical-trials",
  rateLimit: { perSecond: 3, burst: 8 },
  cacheTtlMs: 60 * 60 * 1000, // 1 hour — trial data doesn't change fast
});

// ─── Helper ──────────────────────────────────────────────────────────

/** Build aggFilters string from phase and studyType codes. */
function buildAggFilters(parts: string[]): string | undefined {
  const filtered = parts.filter(Boolean);
  return filtered.length ? filtered.join(",") : undefined;
}

// ─── Studies API ─────────────────────────────────────────────────────

/** Search options for GET /studies. */
export interface SearchTrialsOptions {
  // Query searches (Essie expression syntax)
  query?: string;
  condition?: string;
  intervention?: string;
  sponsor?: string;
  titles?: string;
  outcomes?: string;
  leadSponsor?: string;
  studyId?: string;
  patient?: string;
  location?: string;

  // Filters
  status?: string | string[];
  phase?: string;
  studyType?: string;
  geoFilter?: string;
  filterIds?: string[];
  filterAdvanced?: string;
  aggFilters?: string;

  // Pagination & sorting
  sort?: string[];
  fields?: string[];
  countTotal?: boolean;
  pageSize?: number;
  pageToken?: string;
}

/**
 * Search for clinical trials.
 *
 * @example
 *   const data = await searchTrials({ condition: "breast cancer", status: "RECRUITING" });
 *   const data = await searchTrials({ intervention: "semaglutide", phase: "PHASE3" });
 *   const data = await searchTrials({ geoFilter: "distance(38.9,-77.0,50mi)", condition: "diabetes" });
 */
export async function searchTrials(opts: SearchTrialsOptions): Promise<PagedStudies> {
  // Build aggFilters from phase/studyType (these are NOT valid v2 filter.* params)
  const aggParts: string[] = [];
  if (opts.aggFilters) aggParts.push(opts.aggFilters);
  if (opts.phase && AGG_PHASE_CODES[opts.phase]) {
    aggParts.push(`phase:${AGG_PHASE_CODES[opts.phase]}`);
  }
  if (opts.studyType && AGG_STUDY_TYPE_CODES[opts.studyType]) {
    aggParts.push(`studyType:${AGG_STUDY_TYPE_CODES[opts.studyType]}`);
  }

  const params = qp({
    "query.term": opts.query,
    "query.cond": opts.condition,
    "query.intr": opts.intervention,
    "query.spons": opts.sponsor,
    "query.titles": opts.titles,
    "query.outc": opts.outcomes,
    "query.lead": opts.leadSponsor,
    "query.id": opts.studyId,
    "query.patient": opts.patient,
    "query.locn": opts.location,
    "filter.overallStatus": Array.isArray(opts.status) ? opts.status.join("|") : opts.status,
    "filter.geo": opts.geoFilter,
    "filter.ids": opts.filterIds?.join("|"),
    "filter.advanced": opts.filterAdvanced,
    aggFilters: buildAggFilters(aggParts),
    sort: opts.sort?.join("|"),
    fields: opts.fields?.join("|"),
    countTotal: opts.countTotal ?? true,
    pageSize: opts.pageSize ?? 10,
    pageToken: opts.pageToken,
  });

  return api.get<PagedStudies>("/studies", params);
}

/**
 * Get full details for a specific trial by NCT ID.
 *
 * @example
 *   const study = await getTrialDetail("NCT06000000");
 *   const study = await getTrialDetail("NCT06000000", { fields: ["NCTId", "BriefTitle", "ResultsSection"] });
 */
export async function getTrialDetail(
  nctId: string,
  opts?: { fields?: string[] },
): Promise<Study> {
  return api.get<Study>(`/studies/${encodeURIComponent(nctId)}`, qp({
    fields: opts?.fields?.join("|"),
    markupFormat: "markdown",
  }));
}

/**
 * Get study data model metadata — field names, types, descriptions.
 *
 * @example
 *   const fields = await getStudyMetadata();
 *   const fields = await getStudyMetadata({ includeIndexedOnly: true });
 */
export async function getStudyMetadata(opts?: {
  includeIndexedOnly?: boolean;
  includeHistoricOnly?: boolean;
}): Promise<FieldNode[]> {
  return api.get<FieldNode[]>("/studies/metadata", qp({
    includeIndexedOnly: opts?.includeIndexedOnly,
    includeHistoricOnly: opts?.includeHistoricOnly,
  }));
}

/**
 * Get search area definitions — what fields are searched by each query param.
 *
 * @example
 *   const areas = await getSearchAreas();
 */
export async function getSearchAreas(): Promise<SearchDocument[]> {
  return api.get<SearchDocument[]>("/studies/search-areas");
}

/**
 * Get all enum types and their valid values.
 *
 * @example
 *   const enums = await getEnums();
 *   const statusEnum = enums.find(e => e.type === 'Status');
 */
export async function getEnums(): Promise<EnumInfo[]> {
  return api.get<EnumInfo[]>("/studies/enums");
}

// ─── Stats API ───────────────────────────────────────────────────────

/**
 * Get study JSON size statistics (total studies, avg size, largest).
 *
 * @example
 *   const stats = await getSizeStats();
 *   console.log(`Total studies: ${stats.totalStudies}`);
 */
export async function getSizeStats(): Promise<SizeStats> {
  return api.get<SizeStats>("/stats/size");
}

/**
 * Get field value statistics — top values, counts, ranges for any leaf field.
 *
 * @example
 *   const stats = await getFieldValueStats({ fields: ["Phase"] });
 *   const stats = await getFieldValueStats({ types: ["ENUM"], fields: ["OverallStatus"] });
 */
export async function getFieldValueStats(opts?: {
  types?: string[];
  fields?: string[];
}): Promise<FieldValueStats[]> {
  return api.get<FieldValueStats[]>("/stats/field/values", qp({
    types: opts?.types?.join("|"),
    fields: opts?.fields?.join("|"),
  }));
}

/**
 * Get list/array field size statistics.
 *
 * @example
 *   const stats = await getFieldSizeStats({ fields: ["Phase", "Condition"] });
 */
export async function getFieldSizeStats(opts?: {
  fields?: string[];
}): Promise<ListSizeStats[]> {
  return api.get<ListSizeStats[]>("/stats/field/sizes", qp({
    fields: opts?.fields?.join("|"),
  }));
}

// ─── Version API ─────────────────────────────────────────────────────

/**
 * Get API version and data timestamp.
 *
 * @example
 *   const v = await getVersion();
 *   console.log(`API: ${v.apiVersion}, Data: ${v.dataTimestamp}`);
 */
export async function getVersion(): Promise<VersionInfo> {
  return api.get<VersionInfo>("/version");
}

// ─── Convenience Functions ───────────────────────────────────────────

/**
 * Get trial count breakdown by status for a condition or drug.
 * Makes parallel requests for speed.
 *
 * @example
 *   const stats = await getTrialEnrollmentStats("Alzheimer Disease");
 *   const stats = await getTrialEnrollmentStats("semaglutide", { asIntervention: true });
 */
export async function getTrialEnrollmentStats(
  term: string,
  opts?: { asIntervention?: boolean },
): Promise<{ term: string; statuses: Record<string, number> }> {
  const statuses = [
    "RECRUITING",
    "NOT_YET_RECRUITING",
    "ACTIVE_NOT_RECRUITING",
    "ENROLLING_BY_INVITATION",
    "COMPLETED",
    "SUSPENDED",
    "TERMINATED",
    "WITHDRAWN",
  ];

  // Build base search params — use intervention or condition search
  const baseOpts: SearchTrialsOptions = opts?.asIntervention
    ? { intervention: term }
    : { condition: term };

  // Fire all status queries in parallel for speed
  const results = await Promise.all(
    statuses.map(async (status) => {
      const data = await searchTrials({
        ...baseOpts,
        status,
        pageSize: 0,
        countTotal: true,
        fields: ["NCTId"],
      });
      return [status, data.totalCount ?? 0] as const;
    }),
  );

  const statusMap: Record<string, number> = {};
  for (const [status, count] of results) {
    if (count > 0) statusMap[status] = count;
  }

  return { term, statuses: statusMap };
}

/** Clear the cache. */
export function clearCache(): void {
  api.clearCache();
}
