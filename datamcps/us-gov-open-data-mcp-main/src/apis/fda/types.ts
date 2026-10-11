/**
 * FDA (OpenFDA) types — shared interfaces, result types, and constants.
 *
 * All OpenFDA endpoints return the same meta structure. Each endpoint's results
 * section differs — typed interfaces for each are defined here. Generic result
 * wrappers (`FdaResult<T>`) reduce boilerplate.
 *
 * Docs: https://open.fda.gov/apis/
 */

// ─── Meta / Shared ───────────────────────────────────────────────────

/** Standard OpenFDA response metadata. Present on every response. */
export interface OpenFdaMeta {
  disclaimer: string;
  terms: string;
  license: string;
  last_updated: string;
  results: {
    skip: number;
    limit: number;
    total: number;
  };
}

/** Generic OpenFDA result wrapper. */
export interface FdaResult<T> {
  meta: OpenFdaMeta;
  results: T[];
}

/** Count result — returned by `?count=field` queries on any endpoint. */
export interface CountResult {
  meta?: OpenFdaMeta;
  results: { term: string; count: number }[];
}

/** Common openfda annotation block for drug endpoints. */
export interface OpenFdaDrugAnnotation {
  brand_name?: string[];
  generic_name?: string[];
  manufacturer_name?: string[];
  route?: string[];
  product_type?: string[];
  substance_name?: string[];
  rxcui?: string[];
  spl_id?: string[];
  spl_set_id?: string[];
  package_ndc?: string[];
  product_ndc?: string[];
  application_number?: string[];
  unii?: string[];
  [key: string]: unknown;
}

/** Common openfda annotation block for device endpoints. */
export interface OpenFdaDeviceAnnotation {
  device_name?: string;
  device_class?: string;
  medical_specialty_description?: string;
  regulation_number?: string;
  registration_number?: string[];
  fei_number?: string[];
  k_number?: string[];
  pma_number?: string[];
  [key: string]: unknown;
}

// ─── Shared: Enforcement Recall (drug/food/device share this schema) ─

/** Enforcement recall — used by /drug/enforcement, /food/enforcement, /device/enforcement. */
export interface EnforcementRecall {
  recall_number?: string;
  report_date?: string;
  recall_initiation_date?: string;
  classification?: string;
  reason_for_recall?: string;
  status?: string;
  voluntary_mandated?: string;
  recalling_firm?: string;
  city?: string;
  state?: string;
  country?: string;
  product_description?: string;
  product_quantity?: string;
  distribution_pattern?: string;
  initial_firm_notification?: string;
  event_id?: string;
  openfda?: OpenFdaDrugAnnotation | OpenFdaDeviceAnnotation;
  [key: string]: unknown;
}

// ─── Drug Endpoints ──────────────────────────────────────────────────

/** Drug adverse event report (FAERS). Endpoint: /drug/event.json */
export interface DrugEvent {
  safetyreportid: string;
  receivedate: string;
  receiptdate: string;
  serious: string;
  seriousnessdeath?: string;
  seriousnesshospitalization?: string;
  seriousnesslifethreatening?: string;
  seriousnessdisabling?: string;
  seriousnesscongenitalanomali?: string;
  seriousnessother?: string;
  patient: {
    patientonsetage?: string;
    patientonsetageunit?: string;
    patientsex?: string;
    reaction: { reactionmeddrapt: string; reactionoutcome?: string }[];
    drug: {
      medicinalproduct: string;
      drugindication?: string;
      drugcharacterization?: string;
      openfda?: OpenFdaDrugAnnotation;
    }[];
  };
  [key: string]: unknown;
}

/** Drug product labeling (SPL). Endpoint: /drug/label.json */
export interface DrugLabel {
  id: string;
  set_id?: string;
  effective_time?: string;
  indications_and_usage?: string[];
  warnings?: string[];
  warnings_and_cautions?: string[];
  dosage_and_administration?: string[];
  adverse_reactions?: string[];
  drug_interactions?: string[];
  description?: string[];
  boxed_warning?: string[];
  contraindications?: string[];
  clinical_pharmacology?: string[];
  pregnancy?: string[];
  nursing_mothers?: string[];
  pediatric_use?: string[];
  geriatric_use?: string[];
  overdosage?: string[];
  how_supplied?: string[];
  openfda: OpenFdaDrugAnnotation;
  [key: string]: unknown;
}

/** NDC Directory entry. Endpoint: /drug/ndc.json */
export interface DrugNdc {
  product_ndc?: string;
  product_id?: string;
  spl_id?: string;
  brand_name?: string;
  brand_name_base?: string;
  brand_name_suffix?: string;
  generic_name?: string;
  dosage_form?: string;
  route?: string;
  marketing_start_date?: string;
  marketing_end_date?: string;
  marketing_category?: string;
  application_number?: string;
  pharm_class?: string[];
  dea_schedule?: string;
  listing_expiration_date?: string;
  product_type?: string;
  finished?: boolean;
  active_ingredients?: { name: string; strength: string }[];
  packaging?: { package_ndc: string; description: string; marketing_start_date?: string }[];
  openfda?: OpenFdaDrugAnnotation;
  [key: string]: unknown;
}

/** Drug shortage listing. Endpoint: /drug/shortages.json */
export interface DrugShortage {
  generic_name?: string;
  company_name?: string;
  status?: string;
  dosage_form?: string;
  presentation?: string;
  therapeutic_category?: string[];
  initial_posting_date?: string;
  update_date?: string;
  discontinued_date?: string;
  update_type?: string;
  related_info?: string;
  contact_info?: string;
  package_ndc?: string;
  openfda?: OpenFdaDrugAnnotation;
  [key: string]: unknown;
}

/** FDA-approved drug (Drugs@FDA). Endpoint: /drug/drugsfda.json */
export interface ApprovedDrug {
  application_number?: string;
  sponsor_name?: string;
  products?: {
    brand_name?: string;
    active_ingredients?: { name: string; strength: string }[];
    route?: string;
    dosage_form?: string;
    marketing_status?: string;
  }[];
  submissions?: {
    submission_type?: string;
    submission_number?: string;
    submission_status?: string;
    submission_status_date?: string;
    application_docs?: { id: string; url: string; type: string; title?: string }[];
  }[];
  openfda?: OpenFdaDrugAnnotation;
  [key: string]: unknown;
}

// ─── Device Endpoints ────────────────────────────────────────────────

/** Device adverse event report (MAUDE). Endpoint: /device/event.json */
export interface DeviceEvent {
  event_key?: string;
  report_number?: string;
  date_received?: string;
  event_type?: string;
  device?: {
    brand_name?: string;
    generic_name?: string;
    manufacturer_d_name?: string;
    model_number?: string;
    openfda?: OpenFdaDeviceAnnotation;
  }[];
  mdr_text?: { text: string; text_type_code: string }[];
  [key: string]: unknown;
}

/** 510(k) clearance. Endpoint: /device/510k.json */
export interface Device510k {
  k_number?: string;
  device_name?: string;
  applicant?: string;
  contact?: string;
  date_received?: string;
  decision_date?: string;
  decision_code?: string;
  decision_description?: string;
  product_code?: string;
  statement_or_summary?: string;
  clearance_type?: string;
  advisory_committee?: string;
  advisory_committee_description?: string;
  expedited_review_flag?: string;
  third_party_flag?: string;
  city?: string;
  state?: string;
  country_code?: string;
  zip_code?: string;
  address_1?: string;
  address_2?: string;
  openfda?: OpenFdaDeviceAnnotation;
  [key: string]: unknown;
}

/** Device classification. Endpoint: /device/classification.json */
export interface DeviceClassification {
  device_name?: string;
  device_class?: string;
  product_code?: string;
  regulation_number?: string;
  medical_specialty?: string;
  medical_specialty_description?: string;
  definition?: string;
  review_panel?: string;
  review_code?: string;
  submission_type_id?: string;
  implant_flag?: string;
  life_sustain_support_flag?: string;
  gmp_exempt_flag?: string;
  summary_malfunction_reporting?: string;
  third_party_flag?: string;
  unclassified_reason?: string;
  openfda?: OpenFdaDeviceAnnotation;
  [key: string]: unknown;
}

/** Premarket Approval (PMA). Endpoint: /device/pma.json */
export interface DevicePma {
  pma_number?: string;
  supplement_number?: string;
  supplement_type?: string;
  supplement_reason?: string;
  applicant?: string;
  trade_name?: string;
  generic_name?: string;
  product_code?: string;
  advisory_committee?: string;
  advisory_committee_description?: string;
  date_received?: string;
  decision_date?: string;
  decision_code?: string;
  expedited_review_flag?: string;
  ao_statement?: string;
  docket_number?: string;
  city?: string;
  state?: string;
  zip?: string;
  street_1?: string;
  street_2?: string;
  openfda?: OpenFdaDeviceAnnotation;
  [key: string]: unknown;
}

/** Unique Device Identifier (UDI). Endpoint: /device/udi.json */
export interface DeviceUdi {
  brand_name?: string;
  company_name?: string;
  device_description?: string;
  version_or_model_number?: string;
  catalog_number?: string;
  record_key?: string;
  public_device_record_key?: string;
  record_status?: string;
  publish_date?: string;
  public_version_date?: string;
  public_version_number?: string;
  public_version_status?: string;
  commercial_distribution_status?: string;
  commercial_distribution_end_date?: string;
  labeler_duns_number?: string;
  device_count_in_base_package?: string;
  /** Booleans stored as strings ("true"/"false") */
  is_rx?: string;
  is_otc?: string;
  is_kit?: string;
  is_single_use?: string;
  is_combination_product?: string;
  is_hct_p?: string;
  is_pm_exempt?: string;
  is_direct_marking_exempt?: string;
  is_labeled_as_nrl?: string;
  is_labeled_as_no_nrl?: string;
  has_serial_number?: string;
  has_lot_or_batch_number?: string;
  has_manufacturing_date?: string;
  has_expiration_date?: string;
  has_donation_id_number?: string;
  mri_safety?: string;
  identifiers?: { id: string; type: string; issuing_agency: string }[];
  product_codes?: {
    code: string;
    name: string;
    openfda?: OpenFdaDeviceAnnotation;
  }[];
  gmdn_terms?: { code: string; name: string; definition?: string; implantable?: string; code_status?: string }[];
  customer_contacts?: { phone?: string; email?: string }[];
  sterilization?: { is_sterile?: string; is_sterilization_prior_use?: string; sterilization_methods?: string };
  storage?: { high?: object; low?: object; type?: string }[];
  device_sizes?: { type?: string; value?: string; unit?: string }[];
  [key: string]: unknown;
}

/** Device registration & listing. Endpoint: /device/registrationlisting.json */
export interface DeviceRegistration {
  registration_number?: string;
  fei_number?: string;
  establishment_type?: string[];
  registration?: {
    name?: string;
    owner_operator?: { firm_name?: string; [key: string]: unknown };
    [key: string]: unknown;
  };
  products?: {
    product_code?: string;
    created_date?: string;
    openfda?: OpenFdaDeviceAnnotation;
    [key: string]: unknown;
  }[];
  [key: string]: unknown;
}

/** COVID-19 serology testing evaluation. Endpoint: /device/covid19serology.json */
export interface CovidSerology {
  sample_id?: string;
  sample_no?: string;
  evaluation_id?: string;
  device?: string;
  manufacturer?: string;
  date_performed?: string;
  lot_number?: string;
  type?: string;
  panel?: string;
  group?: string;
  days_from_symptom?: string;
  control?: string;
  antibody_truth?: string;
  antibody_agree?: string;
  igg_truth?: string;
  igg_result?: string;
  igg_agree?: string;
  igg_titer?: string;
  igm_truth?: string;
  igm_result?: string;
  igm_agree?: string;
  igm_titer?: string;
  iga_result?: string;
  iga_agree?: string;
  pan_result?: string;
  pan_agree?: string;
  pan_titer?: string;
  igm_igg_result?: string;
  igm_igg_agree?: string;
  igm_iga_result?: string;
  igm_iga_agree?: string;
  [key: string]: unknown;
}

// ─── Food Endpoints ──────────────────────────────────────────────────

/** Food adverse event report (CAERS). Endpoint: /food/event.json */
export interface FoodAdverseEvent {
  report_number?: string;
  date_created?: string;
  date_started?: string;
  outcomes?: string[];
  products?: { name_brand?: string; industry_name?: string; role?: string }[];
  reactions?: string[];
  consumer?: { age?: string; age_unit?: string; gender?: string };
  [key: string]: unknown;
}

// ─── Animal & Veterinary Endpoints ───────────────────────────────────

/** Animal/Veterinary adverse event. Endpoint: /animalandveterinary/event.json */
export interface AnimalEvent {
  report_id?: string;
  unique_aer_id_number?: string;
  original_receive_date?: string;
  onset_date?: string;
  primary_reporter?: string;
  secondary_reporter?: string;
  type_of_information?: string;
  serious_ae?: boolean;
  number_of_animals_affected?: number;
  number_of_animals_treated?: number;
  treated_for_ae?: boolean;
  animal?: {
    species?: string;
    breed?: { breed_component?: string; is_crossbred?: string };
    gender?: string;
    female_animal_physiological_status?: string;
    reproductive_status?: string;
    age?: { min?: string; max?: string; unit?: string; qualifier?: string };
    weight?: { min?: string; max?: string; unit?: string; qualifier?: string };
    [key: string]: unknown;
  };
  drug?: {
    brand_name?: string;
    lot_number?: string;
    dosage_form?: string;
    manufacturer?: { name?: string; registration_number?: string } | string;
    active_ingredients?: { name: string; dose?: { numerator?: string; denominator?: string } }[];
    atc_vet_code?: string;
    [key: string]: unknown;
  }[];
  reaction?: {
    veddra_version?: string;
    veddra_term_code?: string;
    veddra_term_name?: string;
    accuracy?: string;
  }[];
  outcome?: { medical_status?: string; number_of_animals_affected?: number }[];
  health_assessment_prior_to_exposure?: { assessed_by?: string; condition?: string };
  duration?: { value?: string; unit?: string };
  time_between_exposure_and_onset?: string;
  receiver?: { organization?: string; city?: string; state?: string; country?: string; [key: string]: unknown };
  [key: string]: unknown;
}

// ─── Tobacco Endpoints ───────────────────────────────────────────────

/** Tobacco problem report. Endpoint: /tobacco/problem.json */
export interface TobaccoProblem {
  report_id?: number;
  date_submitted?: string;
  tobacco_products?: string[];
  number_tobacco_products?: number;
  reported_health_problems?: string[];
  number_health_problems?: number;
  reported_product_problems?: string[];
  number_product_problems?: number;
  nonuser_affected?: string;
  [key: string]: unknown;
}

// ─── Other Endpoints ─────────────────────────────────────────────────

/** Historical FDA document (press release). Endpoint: /other/historicaldocument.json */
export interface HistoricalDocument {
  year?: number;
  doc_type?: string;
  text?: string;
  num_of_pages?: number;
  [key: string]: unknown;
}

/** NDC SPL Data Element. Endpoint: /other/nsde.json */
export interface Nsde {
  proprietary_name?: string;
  package_ndc?: string;
  package_ndc11?: string;
  product_type?: string;
  dosage_form?: string;
  marketing_category?: string;
  marketing_start_date?: string;
  marketing_end_date?: string;
  application_number_or_citation?: string;
  [key: string]: unknown;
}

/** Substance data record. Endpoint: /other/substance.json */
export interface SubstanceData {
  uuid?: string;
  unii?: string;
  substance_class?: string;
  status?: string;
  names?: { name?: string; type?: string; [key: string]: unknown }[];
  codes?: { code?: string; code_system?: string; type?: string; url?: string; [key: string]: unknown }[];
  relationships?: unknown[];
  structure?: { formula?: string; smiles?: string; [key: string]: unknown };
  [key: string]: unknown;
}

/** UNII (Unique Ingredient Identifier). Endpoint: /other/unii.json */
export interface Unii {
  unii?: string;
  substance_name?: string;
  [key: string]: unknown;
}

// ─── Constants ───────────────────────────────────────────────────────

/** All OpenFDA endpoint paths, for use in the generic count tool. */
export const FDA_ENDPOINTS = {
  // Drug
  "drug/event": "Drug adverse events (FAERS)",
  "drug/label": "Drug product labeling (SPL)",
  "drug/ndc": "NDC Directory — National Drug Code",
  "drug/enforcement": "Drug recall enforcement reports",
  "drug/drugsfda": "Drugs@FDA approved drugs",
  "drug/shortages": "Drug shortages",
  // Device
  "device/event": "Device adverse events (MAUDE)",
  "device/510k": "510(k) premarket clearances",
  "device/classification": "Device classification",
  "device/enforcement": "Device recall enforcement reports",
  "device/recall": "Device recalls (RES)",
  "device/pma": "Premarket Approval (PMA)",
  "device/registrationlisting": "Device registration & listing",
  "device/udi": "Unique Device Identifier (GUDID)",
  "device/covid19serology": "COVID-19 serology test evaluations",
  // Food
  "food/enforcement": "Food recall enforcement reports",
  "food/event": "Food adverse events (CAERS)",
  // Animal & Veterinary
  "animalandveterinary/event": "Animal/veterinary adverse events",
  // Tobacco
  "tobacco/problem": "Tobacco problem reports",
  // Other
  "other/historicaldocument": "Historical FDA documents (1913–2014)",
  "other/nsde": "NDC SPL Data Elements",
  "other/substance": "Substance data (molecular)",
  "other/unii": "UNII — Unique Ingredient Identifiers",
} as const;

/** Top count fields per endpoint — for the generic count tool description. */
export const FDA_COUNT_FIELDS: Record<string, string[]> = {
  "drug/event": [
    "patient.reaction.reactionmeddrapt.exact",
    "patient.drug.openfda.brand_name.exact",
    "patient.drug.openfda.generic_name.exact",
    "serious",
    "receivedate",
  ],
  "drug/label": [
    "openfda.product_type.exact",
    "openfda.brand_name.exact",
    "openfda.route.exact",
    "openfda.manufacturer_name.exact",
  ],
  "drug/ndc": [
    "pharm_class.exact",
    "dea_schedule",
    "dosage_form.exact",
    "route.exact",
    "marketing_category.exact",
  ],
  "drug/enforcement": [
    "classification.exact",
    "voluntary_mandated.exact",
    "status.exact",
    "state.exact",
  ],
  "drug/drugsfda": [
    "openfda.brand_name.exact",
    "submissions.submission_type.exact",
  ],
  "drug/shortages": [
    "update_type",
    "status.exact",
    "therapeutic_category.exact",
    "dosage_form.exact",
  ],
  "device/event": [
    "event_type.exact",
    "device.generic_name.exact",
  ],
  "device/510k": [
    "country_code",
    "advisory_committee",
    "clearance_type.exact",
    "decision_code",
  ],
  "device/classification": [
    "device_class",
    "medical_specialty.exact",
    "openfda.fei_number",
  ],
  "device/enforcement": [
    "voluntary_mandated.exact",
    "classification.exact",
    "status.exact",
  ],
  "device/pma": [
    "advisory_committee",
    "decision_code",
  ],
  "device/udi": [
    "product_codes.openfda.device_class",
    "is_rx",
    "mri_safety.exact",
  ],
  "food/enforcement": [
    "classification.exact",
    "voluntary_mandated.exact",
    "state.exact",
  ],
  "food/event": [
    "reactions.exact",
    "outcomes.exact",
    "products.industry_name.exact",
  ],
  "animalandveterinary/event": [
    "animal.species.exact",
    "primary_reporter.exact",
    "serious_ae",
  ],
  "tobacco/problem": [
    "tobacco_products.exact",
    "reported_health_problems.exact",
    "nonuser_affected.exact",
  ],
};
