/**
 * Congress.gov types and interfaces.
 *
 * Separated from sdk.ts for clarity. Re-exported via sdk.ts barrel.
 */

// ─── Bill Types ──────────────────────────────────────────────────────

/** Congress Bill. */
export interface CongressBill {
  type?: string;
  number?: number;
  title?: string;
  congress?: number;
  introducedDate?: string;
  url?: string;
  sponsor?: { name?: string; party?: string; state?: string };
  latestAction?: { text?: string; actionDate?: string };
  [key: string]: unknown;
}

/** Congress Bill Detail. */
export interface CongressBillDetail {
  type?: string;
  number?: number;
  title?: string;
  congress?: number;
  introducedDate?: string;
  sponsors?: { firstName?: string; lastName?: string; party?: string; state?: string }[];
  latestAction?: { text?: string; actionDate?: string };
  laws?: { type?: string; number?: string }[];
  policyArea?: { name?: string };
  [key: string]: unknown;
}

/** Congress Cosponsor. */
export interface CongressCosponsor {
  bioguideId?: string;
  /** Some endpoints spell it bioguidId (missing 'e') */
  bioguidId?: string;
  firstName?: string;
  lastName?: string;
  fullName?: string;
  party?: string;
  state?: string;
  district?: number;
  isOriginalCosponsor?: boolean;
  sponsorshipDate?: string;
  url?: string;
  [key: string]: unknown;
}

/** Congress Bill Title. */
export interface CongressBillTitle {
  title?: string;
  titleType?: string;
  titleTypeCode?: number;
  updateDate?: string;
  billTextVersionCode?: string;
  billTextVersionName?: string;
  [key: string]: unknown;
}

/** Congress Law. */
export interface CongressLaw {
  type?: string;
  number?: number;
  title?: string;
  latestAction?: { actionDate?: string; text?: string };
  url?: string;
  [key: string]: unknown;
}

/** Congress Sponsored Bill. */
export interface CongressSponsoredBill {
  type?: string;
  number?: number;
  title?: string;
  congress?: number;
  introducedDate?: string;
  latestAction?: { text?: string; actionDate?: string };
  [key: string]: unknown;
}

/** Congress Related Bill. */
export interface CongressRelatedBill {
  type?: string;
  number?: number;
  congress?: number;
  title?: string;
  relationshipDetails?: { type?: string; identifiedBy?: string }[];
  latestAction?: { text?: string; actionDate?: string };
  url?: string;
  [key: string]: unknown;
}

/** Congress Action. */
export interface CongressAction {
  actionDate?: string;
  text?: string;
  type?: string;
  actionCode?: string;
  sourceSystem?: { code?: number; name?: string };
  committees?: { systemCode?: string; name?: string; url?: string }[];
  recordedVotes?: { rollNumber?: number; url?: string; chamber?: string; congress?: number; date?: string; sessionNumber?: number }[];
  [key: string]: unknown;
}

/** Congress Subject. */
export interface CongressSubject {
  name?: string;
  updateDate?: string;
  [key: string]: unknown;
}

/** Congress Summary. */
export interface CongressSummary {
  versionCode?: string;
  actionDate?: string;
  actionDesc?: string;
  text?: string;
  updateDate?: string;
  [key: string]: unknown;
}

/** Standalone summary from the /summaries endpoint (includes bill reference). */
export interface CongressStandaloneSummary extends CongressSummary {
  bill?: {
    congress?: number;
    number?: string;
    originChamber?: string;
    originChamberCode?: string;
    title?: string;
    type?: string;
    url?: string;
  };
  currentChamber?: string;
  currentChamberCode?: string;
  lastSummaryUpdateDate?: string;
}

/** Congress Text Version. */
export interface CongressTextVersion {
  date?: string;
  type?: string;
  url?: string;
  formats?: { type?: string; url?: string }[];
  [key: string]: unknown;
}

// ─── Member Types ────────────────────────────────────────────────────

/** Congress Member. */
export interface CongressMember {
  name?: string;
  firstName?: string;
  lastName?: string;
  party?: string;
  partyName?: string;
  state?: string;
  chamber?: string;
  district?: number;
  bioguideId?: string;
  startYear?: number;
  endYear?: number;
  terms?: unknown;
  [key: string]: unknown;
}

/** Congress Member Detail. */
export interface CongressMemberDetail {
  bioguideId?: string;
  firstName?: string;
  middleName?: string;
  lastName?: string;
  directOrderName?: string;
  invertedOrderName?: string;
  honorificName?: string;
  birthYear?: string;
  deathYear?: string;
  party?: string;
  state?: string;
  district?: number;
  partyHistory?: { partyName?: string; startYear?: number; endYear?: number }[];
  terms?: { chamber?: string; congress?: number; startYear?: number; endYear?: number; memberType?: string; stateCode?: string; stateName?: string; district?: number }[];
  depiction?: { imageUrl?: string; attribution?: string };
  currentMember?: boolean;
  officialWebsiteUrl?: string;
  [key: string]: unknown;
}

// ─── Vote Types ──────────────────────────────────────────────────────

/** Congress Vote Summary (House — from Congress.gov API or clerk.house.gov). */
export interface CongressVoteSummary {
  rollCallNumber?: number;
  voteNumber?: number;
  date?: string;
  startDate?: string;
  question?: string;
  voteQuestion?: string;
  result?: string;
  description?: string;
  legislationNumber?: string;
  legislationType?: string;
  legislationUrl?: string;
  voteType?: string;
  votePartyTotal?: { voteParty: string; yeaTotal: number; nayTotal: number; notVotingTotal: number; presentTotal: number }[];
  bill?: { type?: string; number?: number; title?: string };
  [key: string]: unknown;
}

/** Congress Vote Member (House). */
export interface CongressVoteMember {
  bioguideID?: string;
  firstName?: string;
  lastName?: string;
  voteParty?: string;
  voteCast?: string;
  voteState?: string;
  /** Mapped from voteParty for convenience */
  party?: string;
  /** Mapped from voteCast for convenience */
  votePosition?: string;
  [key: string]: unknown;
}

/** Senate Vote Summary (from senate.gov XML). */
export interface SenateVoteSummary {
  congress: number;
  session: number;
  voteNumber: number;
  date: string;
  question: string;
  result: string;
  title: string;
  description: string;
  majorityRequired: string;
  document?: {
    type: string;
    number: string;
    name: string;
    title: string;
  };
  count: {
    yeas: number;
    nays: number;
    present: number;
    absent: number;
  };
  tieBreaker?: { byWhom: string; vote: string };
}

/** Senate Vote Member (from senate.gov XML). */
export interface SenateVoteMember {
  fullName: string;
  firstName: string;
  lastName: string;
  party: string;
  state: string;
  voteCast: string;
}

// ─── Amendment Types ─────────────────────────────────────────────────

/** Congress Amendment. */
export interface CongressAmendment {
  number?: number | string;
  type?: string;
  congress?: number;
  description?: string;
  purpose?: string;
  latestAction?: { text?: string; actionDate?: string };
  sponsor?: { firstName?: string; lastName?: string; party?: string; state?: string; bioguideId?: string };
  url?: string;
  [key: string]: unknown;
}

// ─── Committee Types ─────────────────────────────────────────────────

/** Congress Committee Ref (as returned in bill sub-resources). */
export interface CongressCommitteeRef {
  systemCode?: string;
  name?: string;
  chamber?: string;
  type?: string;
  url?: string;
  activities?: { name?: string; date?: string }[];
  [key: string]: unknown;
}

/** Congress Committee (full detail). */
export interface CongressCommittee {
  systemCode?: string;
  name?: string;
  chamber?: string;
  type?: string;
  committeeTypeCode?: string;
  parent?: { systemCode?: string; name?: string; url?: string };
  subcommittees?: { systemCode?: string; name?: string; url?: string }[];
  url?: string;
  isCurrent?: boolean;
  committeeWebsiteUrl?: string;
  history?: { libraryOfCongressName?: string; officialName?: string; startDate?: string; endDate?: string; updateDate?: string }[];
  bills?: { count?: number; url?: string };
  reports?: { count?: number; url?: string };
  communications?: { count?: number; url?: string };
  updateDate?: string;
  [key: string]: unknown;
}

/** Committee Report (from /committee-report endpoints). */
export interface CongressCommitteeReport {
  chamber?: string;
  citation?: string;
  congress?: number;
  number?: number;
  part?: number;
  type?: string;
  updateDate?: string;
  url?: string;
  /** Detail-only fields */
  associatedBill?: { congress?: number; number?: string; type?: string; url?: string }[];
  isConferenceReport?: boolean;
  issueDate?: string;
  reportType?: string;
  sessionNumber?: number;
  title?: string;
  text?: { count?: number; url?: string };
  [key: string]: unknown;
}

/** Committee Print (from /committee-print endpoints). */
export interface CongressCommitteePrint {
  chamber?: string;
  congress?: number;
  jacketNumber?: number;
  updateDate?: string;
  url?: string;
  /** Detail-only fields */
  citation?: string;
  number?: string;
  title?: string;
  committees?: { name?: string; systemCode?: string; url?: string }[];
  associatedBills?: { congress?: number; number?: string; type?: string; url?: string }[];
  text?: { count?: number; url?: string };
  [key: string]: unknown;
}

/** Committee Meeting (from /committee-meeting endpoints). */
export interface CongressCommitteeMeeting {
  chamber?: string;
  congress?: number;
  eventid?: string;
  updateDate?: string;
  url?: string;
  /** Detail-only fields */
  date?: string;
  title?: string;
  type?: string;
  meetingStatus?: string;
  location?: { building?: string; room?: string };
  committees?: { name?: string; systemCode?: string; url?: string }[];
  meetingDocuments?: { name?: string; description?: string; documentType?: string; format?: string; url?: string }[];
  witnesses?: { name?: string; organization?: string; position?: string }[];
  videos?: { name?: string; url?: string }[];
  relatedItems?: { bills?: unknown[]; nominations?: unknown[]; treaties?: unknown[] }[];
  [key: string]: unknown;
}

// ─── Hearing Types ───────────────────────────────────────────────────

/** Hearing (from /hearing endpoints). */
export interface CongressHearing {
  chamber?: string;
  congress?: number;
  jacketNumber?: number;
  updateDate?: string;
  url?: string;
  /** Detail-only fields */
  citation?: string;
  title?: string;
  dates?: string[];
  committees?: { name?: string; systemCode?: string; url?: string }[];
  formats?: { type?: string; url?: string }[];
  associatedMeeting?: { eventId?: string; url?: string };
  libraryOfCongressidentifier?: string;
  [key: string]: unknown;
}

// ─── Nomination & Treaty Types ───────────────────────────────────────

/** Congress Nomination. */
export interface CongressNomination {
  number?: number | string;
  congress?: number;
  description?: string;
  receivedDate?: string;
  organization?: string;
  nominees?: { firstName?: string; lastName?: string; state?: string; position?: string }[];
  latestAction?: { text?: string; actionDate?: string };
  url?: string;
  [key: string]: unknown;
}

/** Congress Treaty. */
export interface CongressTreaty {
  number?: number | string;
  suffix?: string;
  congress?: number;
  congressReceived?: number;
  topic?: string;
  transmittedDate?: string;
  inForceDate?: string;
  resolutionText?: string;
  latestAction?: { text?: string; actionDate?: string };
  url?: string;
  [key: string]: unknown;
}

// ─── CRS Report Types ────────────────────────────────────────────────

/** Congress CRS Report. */
export interface CongressCrsReport {
  /** Report ID (e.g. 'R47175') — returned as `id` by detail endpoint */
  id?: string;
  /** Report number — same as id but used in list context */
  reportNumber?: string;
  title?: string;
  /** Content type (e.g. 'Reports') */
  contentType?: string;
  /** 'Active' or 'Archived' */
  status?: string;
  type?: string;
  activeRecord?: boolean;
  publishDate?: string;
  updateDate?: string;
  version?: number;
  /** Plain-text CRS summary of the report */
  summary?: string;
  authors?: { author?: string }[];
  topics?: { topic?: string }[];
  formats?: { format?: string; url?: string }[];
  relatedMaterials?: {
    URL?: string;
    congress?: number;
    number?: string;
    title?: string;
    type?: string;
  }[];
  url?: string;
  [key: string]: unknown;
}

// ─── Congressional Record Types ──────────────────────────────────────

/** Congress Congressional Record. */
export interface CongressCongressionalRecord {
  issueNumber?: string;
  volumeNumber?: string;
  issueDate?: string;
  congress?: number;
  sessionNumber?: number;
  url?: string;
  [key: string]: unknown;
}

/** Daily Congressional Record issue (from /daily-congressional-record endpoints). */
export interface CongressDailyCongressionalRecord {
  congress?: string | number;
  issueDate?: string;
  issueNumber?: string;
  sessionNumber?: string | number;
  updateDate?: string;
  url?: string;
  volumeNumber?: string | number;
  /** Detail-only: full issue data */
  fullIssue?: {
    articles?: { count?: number; url?: string };
    entireIssue?: { part?: string; type?: string; url?: string }[];
    sections?: { name?: string; startPage?: string; endPage?: string; text?: { type?: string; url?: string }[] }[];
  };
  [key: string]: unknown;
}

/** Bound Congressional Record (from /bound-congressional-record endpoints). */
export interface CongressBoundCongressionalRecord {
  congress?: number;
  date?: string;
  sessionNumber?: number;
  updateDate?: string;
  url?: string;
  volumeNumber?: number;
  [key: string]: unknown;
}

// ─── Communication Types ─────────────────────────────────────────────

/** House Communication (from /house-communication endpoints). */
export interface CongressHouseCommunication {
  chamber?: string;
  communicationType?: { code?: string; name?: string };
  congress?: number;
  congressNumber?: number;
  number?: string | number;
  updateDate?: string;
  url?: string;
  /** Detail-only fields */
  abstract?: string;
  committees?: { name?: string; systemCode?: string; url?: string; referralDate?: string }[];
  congressionalRecordDate?: string;
  isRulemaking?: string;
  legalAuthority?: string;
  matchingRequirements?: { number?: number; url?: string }[];
  reportNature?: string;
  sessionNumber?: number;
  submittingAgency?: string;
  submittingOfficial?: string;
  [key: string]: unknown;
}

/** House Requirement (from /house-requirement endpoints). */
export interface CongressHouseRequirement {
  number?: number;
  updateDate?: string;
  url?: string;
  /** Detail-only fields */
  activeRecord?: boolean;
  frequency?: string;
  legalAuthority?: string;
  nature?: string;
  parentAgency?: string;
  submittingAgency?: string;
  matchingCommunications?: { count?: number; url?: string };
  [key: string]: unknown;
}

/** Senate Communication (from /senate-communication endpoints). */
export interface CongressSenateCommunication {
  chamber?: string;
  communicationType?: { code?: string; name?: string };
  congress?: number;
  number?: string | number;
  updateDate?: string;
  url?: string;
  /** Detail-only fields */
  abstract?: string;
  committees?: { name?: string; systemCode?: string; url?: string; referralDate?: string }[];
  congressionalRecordDate?: string;
  sessionNumber?: number;
  [key: string]: unknown;
}

// ─── Congress Info ───────────────────────────────────────────────────

/** Congress session info. */
export interface CongressInfo {
  name?: string;
  startYear?: string;
  endYear?: string;
  number?: number;
  sessions?: { chamber?: string; number?: number; startDate?: string; endDate?: string }[];
  url?: string;
  updateDate?: string;
  [key: string]: unknown;
}
