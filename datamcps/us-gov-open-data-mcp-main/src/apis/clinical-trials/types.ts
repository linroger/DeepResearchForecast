/**
 * ClinicalTrials.gov types — shared interfaces, result types, and constants.
 *
 * Based on ClinicalTrials.gov REST API v2.0.5 OpenAPI spec.
 * All study data uses JSON with camelCase field names and UPPERCASE enum values.
 *
 * Docs: https://clinicaltrials.gov/data-api/api
 */

// ─── Study Data Model ────────────────────────────────────────────────

/** Partial date struct — with date and actual/estimated type. */
export interface DateStruct {
  date?: string;
  type?: "ACTUAL" | "ESTIMATED";
}

/** Enrollment information. */
export interface EnrollmentInfo {
  count?: number;
  type?: "ACTUAL" | "ESTIMATED";
}

/** Identification module. */
export interface IdentificationModule {
  nctId?: string;
  nctIdAliases?: string[];
  orgStudyIdInfo?: { id?: string; type?: string; link?: string };
  secondaryIdInfos?: Array<{ id?: string; type?: string; domain?: string }>;
  briefTitle?: string;
  officialTitle?: string;
  acronym?: string;
  organization?: { fullName?: string; class?: string };
}

/** Status module. */
export interface StatusModule {
  statusVerifiedDate?: string;
  overallStatus?: string;
  lastKnownStatus?: string;
  delayedPosting?: boolean;
  whyStopped?: string;
  expandedAccessInfo?: { hasExpandedAccess?: boolean; nctId?: string; statusForNctId?: string };
  startDateStruct?: DateStruct;
  primaryCompletionDateStruct?: DateStruct;
  completionDateStruct?: DateStruct;
  studyFirstSubmitDate?: string;
  studyFirstSubmitQcDate?: string;
  studyFirstPostDateStruct?: DateStruct;
  resultsWaived?: boolean;
  resultsFirstSubmitDate?: string;
  resultsFirstPostDateStruct?: DateStruct;
  lastUpdateSubmitDate?: string;
  lastUpdatePostDateStruct?: DateStruct;
}

/** Sponsor/collaborators module. */
export interface SponsorCollaboratorsModule {
  responsibleParty?: {
    type?: string;
    investigatorFullName?: string;
    investigatorTitle?: string;
    investigatorAffiliation?: string;
  };
  leadSponsor?: { name?: string; class?: string };
  collaborators?: Array<{ name?: string; class?: string }>;
}

/** Oversight module. */
export interface OversightModule {
  oversightHasDmc?: boolean;
  isFdaRegulatedDrug?: boolean;
  isFdaRegulatedDevice?: boolean;
  isUnapprovedDevice?: boolean;
  isPpsd?: boolean;
  isUsExport?: boolean;
  fdaaa801Violation?: boolean;
}

/** Description module. */
export interface DescriptionModule {
  briefSummary?: string;
  detailedDescription?: string;
}

/** Conditions module. */
export interface ConditionsModule {
  conditions?: string[];
  keywords?: string[];
}

/** Design module. */
export interface DesignModule {
  studyType?: string;
  phases?: string[];
  designInfo?: {
    allocation?: string;
    interventionModel?: string;
    interventionModelDescription?: string;
    primaryPurpose?: string;
    observationalModel?: string;
    timePerspective?: string;
    maskingInfo?: {
      masking?: string;
      maskingDescription?: string;
      whoMasked?: string[];
    };
  };
  enrollmentInfo?: EnrollmentInfo;
  patientRegistry?: boolean;
  targetDuration?: string;
}

/** Arms/interventions module. */
export interface ArmsInterventionsModule {
  armGroups?: Array<{
    label?: string;
    type?: string;
    description?: string;
    interventionNames?: string[];
  }>;
  interventions?: Array<{
    type?: string;
    name?: string;
    description?: string;
    armGroupLabels?: string[];
    otherNames?: string[];
  }>;
}

/** Outcomes module. */
export interface OutcomesModule {
  primaryOutcomes?: Array<{ measure?: string; description?: string; timeFrame?: string }>;
  secondaryOutcomes?: Array<{ measure?: string; description?: string; timeFrame?: string }>;
  otherOutcomes?: Array<{ measure?: string; description?: string; timeFrame?: string }>;
}

/** Eligibility module. */
export interface EligibilityModule {
  eligibilityCriteria?: string;
  healthyVolunteers?: boolean;
  sex?: string;
  genderBased?: boolean;
  genderDescription?: string;
  minimumAge?: string;
  maximumAge?: string;
  stdAges?: string[];
  studyPopulation?: string;
  samplingMethod?: string;
}

/** Location within a trial. */
export interface TrialLocation {
  facility?: string;
  status?: string;
  city?: string;
  state?: string;
  zip?: string;
  country?: string;
  contacts?: Array<{ name?: string; role?: string; phone?: string; email?: string }>;
  geoPoint?: { lat?: number; lon?: number };
}

/** Contacts/locations module. */
export interface ContactsLocationsModule {
  centralContacts?: Array<{ name?: string; role?: string; phone?: string; email?: string }>;
  overallOfficials?: Array<{ name?: string; affiliation?: string; role?: string }>;
  locations?: TrialLocation[];
}

/** References module. */
export interface ReferencesModule {
  references?: Array<{ pmid?: string; type?: string; citation?: string }>;
  seeAlsoLinks?: Array<{ label?: string; url?: string }>;
}

/** IPD Sharing module. */
export interface IpdSharingStatementModule {
  ipdSharing?: string;
  description?: string;
  infoTypes?: string[];
  timeFrame?: string;
  accessCriteria?: string;
  url?: string;
}

/** Protocol section — contains all registered trial information. */
export interface ProtocolSection {
  identificationModule?: IdentificationModule;
  statusModule?: StatusModule;
  sponsorCollaboratorsModule?: SponsorCollaboratorsModule;
  oversightModule?: OversightModule;
  descriptionModule?: DescriptionModule;
  conditionsModule?: ConditionsModule;
  designModule?: DesignModule;
  armsInterventionsModule?: ArmsInterventionsModule;
  outcomesModule?: OutcomesModule;
  eligibilityModule?: EligibilityModule;
  contactsLocationsModule?: ContactsLocationsModule;
  referencesModule?: ReferencesModule;
  ipdSharingStatementModule?: IpdSharingStatementModule;
}

/** Adverse event stats. */
export interface EventStats {
  groupId?: string;
  numEvents?: number;
  numAffected?: number;
  numAtRisk?: number;
}

/** Adverse event. */
export interface AdverseEvent {
  term?: string;
  organSystem?: string;
  sourceVocabulary?: string;
  assessmentType?: string;
  notes?: string;
  stats?: EventStats[];
}

/** Event group (arm in adverse events). */
export interface EventGroup {
  id?: string;
  title?: string;
  description?: string;
  deathsNumAffected?: number;
  deathsNumAtRisk?: number;
  seriousNumAffected?: number;
  seriousNumAtRisk?: number;
  otherNumAffected?: number;
  otherNumAtRisk?: number;
}

/** Outcome measure. */
export interface OutcomeMeasure {
  type?: string;
  title?: string;
  description?: string;
  populationDescription?: string;
  reportingStatus?: string;
  paramType?: string;
  unitOfMeasure?: string;
  timeFrame?: string;
  groups?: Array<{ id?: string; title?: string; description?: string }>;
  [key: string]: unknown;
}

/** Results section — only present for studies with posted results. */
export interface ResultsSection {
  participantFlowModule?: {
    preAssignmentDetails?: string;
    recruitmentDetails?: string;
    groups?: Array<{ id?: string; title?: string; description?: string }>;
    periods?: Array<{ title?: string; milestones?: unknown[]; dropWithdraws?: unknown[] }>;
  };
  baselineCharacteristicsModule?: {
    populationDescription?: string;
    groups?: Array<{ id?: string; title?: string; description?: string }>;
    measures?: unknown[];
  };
  outcomeMeasuresModule?: {
    outcomeMeasures?: OutcomeMeasure[];
  };
  adverseEventsModule?: {
    frequencyThreshold?: string;
    timeFrame?: string;
    description?: string;
    eventGroups?: EventGroup[];
    seriousEvents?: AdverseEvent[];
    otherEvents?: AdverseEvent[];
  };
  moreInfoModule?: {
    limitationsAndCaveats?: { description?: string };
    pointOfContact?: { title?: string; organization?: string; email?: string };
  };
}

/** Derived section. */
export interface DerivedSection {
  miscInfoModule?: { versionHolder?: string };
  conditionBrowseModule?: { meshes?: Array<{ id?: string; term?: string }> };
  interventionBrowseModule?: { meshes?: Array<{ id?: string; term?: string }> };
}

/** Complete Study object returned by the API. */
export interface Study {
  protocolSection?: ProtocolSection;
  resultsSection?: ResultsSection;
  derivedSection?: DerivedSection;
  hasResults?: boolean;
}

// ─── API Response Types ──────────────────────────────────────────────

/** Paginated studies response from GET /studies. */
export interface PagedStudies {
  studies: Study[];
  totalCount?: number;
  nextPageToken?: string;
}

/** Study data model field node from GET /studies/metadata. */
export interface FieldNode {
  name: string;
  piece: string;
  sourceType: string;
  type: string;
  title?: string;
  description?: string;
  isEnum?: boolean;
  nested?: boolean;
  synonyms?: boolean;
  maxChars?: number;
  children?: FieldNode[];
}

/** Search area from GET /studies/search-areas. */
export interface SearchArea {
  name: string;
  param?: string;
  uiLabel?: string;
  parts: Array<{
    type: string;
    pieces: string[];
    weight: number;
    isEnum: boolean;
    isSynonyms: boolean;
  }>;
}

/** Search document (group of search areas). */
export interface SearchDocument {
  name: string;
  areas: SearchArea[];
}

/** Enum info from GET /studies/enums. */
export interface EnumInfo {
  type: string;
  pieces: string[];
  values: Array<{
    value: string;
    legacyValue: string;
    exceptions?: Record<string, string>;
  }>;
}

/** Field value statistics from GET /stats/field/values. */
export interface FieldValueStats {
  field: string;
  piece: string;
  type: string;
  missingStudiesCount: number;
  uniqueValuesCount: number;
  topValues?: Array<{ value: string; studiesCount: number }>;
  /** For date fields */
  min?: string;
  max?: string;
  formats?: string[];
  /** For numeric fields */
  avg?: number;
  /** For boolean fields */
  trueCount?: number;
  falseCount?: number;
}

/** List field size stats from GET /stats/field/sizes. */
export interface ListSizeStats {
  field: string;
  piece: string;
  uniqueSizesCount: number;
  minSize?: number;
  maxSize?: number;
  topSizes?: Array<{ size: number; studiesCount: number }>;
}

/** Study size statistics from GET /stats/size. */
export interface SizeStats {
  totalStudies: number;
  averageSizeBytes: number;
  largestStudies: Array<{ id: string; sizeBytes: number }>;
  percentiles: Record<string, number>;
  ranges: Array<{ sizeRange: string; studiesCount: number }>;
}

/** API version from GET /version. */
export interface VersionInfo {
  apiVersion: string;
  dataTimestamp?: string;
}

// ─── Enum Constants ──────────────────────────────────────────────────

/** Trial overall status values (14 values). */
export const TRIAL_STATUSES = {
  RECRUITING: "Currently recruiting participants",
  NOT_YET_RECRUITING: "Approved but not yet recruiting",
  ACTIVE_NOT_RECRUITING: "Ongoing but no longer recruiting",
  COMPLETED: "Trial has concluded",
  ENROLLING_BY_INVITATION: "Recruiting by invitation only",
  SUSPENDED: "Temporarily halted",
  TERMINATED: "Stopped early",
  WITHDRAWN: "Withdrawn before enrollment",
  AVAILABLE: "Expanded access available",
  NO_LONGER_AVAILABLE: "Expanded access no longer available",
  TEMPORARILY_NOT_AVAILABLE: "Expanded access temporarily unavailable",
  APPROVED_FOR_MARKETING: "Approved for marketing",
  WITHHELD: "Study record withheld",
  UNKNOWN: "Unknown status (legacy records)",
} as const;

/** Study phases (6 values). */
export const TRIAL_PHASES = {
  EARLY_PHASE1: "Early Phase 1 (exploratory)",
  PHASE1: "Phase 1 (safety/dosage in small group)",
  PHASE2: "Phase 2 (efficacy/side effects in larger group)",
  PHASE3: "Phase 3 (large-scale efficacy confirmation)",
  PHASE4: "Phase 4 (post-market surveillance)",
  NA: "Not applicable (non-drug studies)",
} as const;

/** Study types (3 values). */
export const STUDY_TYPES = {
  INTERVENTIONAL: "Testing a drug, device, or procedure",
  OBSERVATIONAL: "Observing health outcomes without intervention",
  EXPANDED_ACCESS: "Making experimental treatment available outside trial",
} as const;

/** Intervention types (11 values). */
export const INTERVENTION_TYPES = {
  DRUG: "Drug (pharmaceutical agent)",
  BIOLOGICAL: "Biological (vaccine, blood product, gene therapy)",
  DEVICE: "Device (medical device or instrument)",
  PROCEDURE: "Procedure (surgical or other clinical procedure)",
  RADIATION: "Radiation therapy",
  BEHAVIORAL: "Behavioral intervention",
  GENETIC: "Genetic (gene transfer, stem cell, etc.)",
  DIETARY_SUPPLEMENT: "Dietary supplement",
  COMBINATION_PRODUCT: "Combination product (drug+device, etc.)",
  DIAGNOSTIC_TEST: "Diagnostic test",
  OTHER: "Other intervention type",
} as const;

/** Agency/sponsor class (9 values). */
export const AGENCY_CLASSES = {
  NIH: "National Institutes of Health",
  FED: "Other U.S. Federal Agency",
  OTHER_GOV: "Other Government (non-U.S.)",
  INDUSTRY: "Industry/commercial sponsor",
  INDIV: "Individual investigator",
  NETWORK: "Research network/consortium",
  AMBIG: "Ambiguous classification",
  OTHER: "Other sponsor type",
  UNKNOWN: "Unknown classification",
} as const;

/** Standard age groups (3 values). */
export const STANDARD_AGES = {
  CHILD: "Child (birth to 17)",
  ADULT: "Adult (18-64)",
  OLDER_ADULT: "Older Adult (65+)",
} as const;

/** Sex eligibility (3 values). */
export const SEX_VALUES = {
  ALL: "All sexes eligible",
  FEMALE: "Female only",
  MALE: "Male only",
} as const;

/** Field stats types for /stats/field/values. */
export const FIELD_STATS_TYPES = {
  ENUM: "Enumeration field",
  STRING: "Free-text string field",
  DATE: "Date field",
  INTEGER: "Integer numeric field",
  NUMBER: "Floating-point numeric field",
  BOOLEAN: "Boolean (true/false) field",
} as const;

/** aggFilters shorthand codes for phases. */
export const AGG_PHASE_CODES: Record<string, string> = {
  EARLY_PHASE1: "early_phase1",
  PHASE1: "1",
  PHASE2: "2",
  PHASE3: "3",
  PHASE4: "4",
  NA: "not_applicable",
};

/** aggFilters shorthand codes for study types. */
export const AGG_STUDY_TYPE_CODES: Record<string, string> = {
  INTERVENTIONAL: "int",
  OBSERVATIONAL: "obs",
  EXPANDED_ACCESS: "exp",
};

/** Default fields requested for search results (keeps response compact). */
export const SEARCH_DEFAULT_FIELDS = [
  "NCTId",
  "BriefTitle",
  "OverallStatus",
  "Phase",
  "StudyType",
  "LeadSponsorName",
  "LeadSponsorClass",
  "Condition",
  "InterventionName",
  "InterventionType",
  "EnrollmentCount",
  "EnrollmentType",
  "StartDate",
  "PrimaryCompletionDate",
  "HasResults",
] as const;
