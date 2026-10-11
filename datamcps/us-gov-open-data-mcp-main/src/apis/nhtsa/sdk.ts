/**
 * NHTSA SDK — typed API client for vehicle recalls, complaints, safety ratings,
 * VIN decoding, and car seat inspection stations.
 *
 * Standalone — no MCP server required. Usage:
 *
 *   import { getRecalls, getComplaints, decodeVin } from "us-gov-open-data-mcp/sdk/nhtsa";
 *
 * No API key required.
 * Docs: https://www.nhtsa.gov/nhtsa-datasets-and-apis
 */

import { createClient } from "../../shared/client.js";

// ─── Clients ─────────────────────────────────────────────────────────

const api = createClient({
  baseUrl: "https://api.nhtsa.gov",
  name: "nhtsa",
  rateLimit: { perSecond: 5, burst: 10 },
  cacheTtlMs: 60 * 60 * 1000,
});

const vpicApi = createClient({
  baseUrl: "https://vpic.nhtsa.dot.gov/api",
  name: "nhtsa-vpic",
  rateLimit: { perSecond: 5, burst: 10 },
  cacheTtlMs: 24 * 60 * 60 * 1000,
});

// ─── Types ───────────────────────────────────────────────────────────

/** Standard NHTSA API response wrapper. */
interface NhtsaResponse<T> { Count?: number; count?: number; Message?: string; message?: string; results?: T[]; Results?: T[] }

/** Extract results from either `results` or `Results` field. */
function extractResults<T>(res: NhtsaResponse<T>): T[] { return res?.results ?? res?.Results ?? []; }

/** Recall record. */
export interface Recall {
  Manufacturer?: string;
  NHTSACampaignNumber?: string;
  parkIt?: boolean;
  parkOutSide?: boolean;
  ReportReceivedDate?: string;
  Component?: string;
  Summary?: string;
  Consequence?: string;
  Remedy?: string;
  Notes?: string;
  ModelYear?: string;
  Make?: string;
  Model?: string;
  NHTSAActionNumber?: string;
  [key: string]: unknown;
}

/** Complaint record. */
export interface Complaint {
  odiNumber?: number;
  manufacturer?: string;
  crash?: boolean;
  fire?: boolean;
  numberOfInjuries?: number;
  numberOfDeaths?: number;
  dateOfIncident?: string;
  dateComplaintFiled?: string;
  vin?: string;
  components?: string;
  summary?: string;
  products?: { type?: string; productYear?: string; productMake?: string; productModel?: string; manufacturer?: string }[];
  [key: string]: unknown;
}

/** VIN decode result. */
export interface VinResult {
  Make?: string; Model?: string; ModelYear?: string; Manufacturer?: string;
  VehicleType?: string; BodyClass?: string; DriveType?: string;
  FuelTypePrimary?: string; EngineModel?: string; EngineCylinders?: string;
  DisplacementL?: string; TransmissionStyle?: string;
  PlantCity?: string; PlantCountry?: string;
  ErrorCode?: string; ErrorText?: string;
  [key: string]: unknown;
}

/** Safety rating vehicle variant. */
export interface SafetyRatingVehicle {
  VehicleId?: number; VehicleDescription?: string;
  ModelYear?: number; Make?: string; Model?: string;
  [key: string]: unknown;
}

/** Safety rating detail. */
export interface SafetyRating {
  VehicleId?: number; VehicleDescription?: string;
  OverallRating?: string; OverallFrontCrashRating?: string;
  FrontCrashDriversideRating?: string; FrontCrashPassengersideRating?: string;
  OverallSideCrashRating?: string; SideCrashDriversideRating?: string;
  SideCrashPassengersideRating?: string; RolloverRating?: string;
  RolloverPossibility?: number; ComplaintsCount?: number;
  RecallsCount?: number; InvestigationCount?: number;
  NHTSAElectronicStabilityControl?: string;
  NHTSAForwardCollisionWarning?: string;
  NHTSALaneDepartureWarning?: string;
  [key: string]: unknown;
}

/** Car seat inspection station. */
export interface CssiStation {
  name?: string; address?: string; city?: string; state?: string;
  zip?: string; phone?: string; lat?: number; long?: number;
  spanishSpeaking?: boolean; cpsWeek?: boolean;
  [key: string]: unknown;
}

/** Product listing (model year, make, or model). */
export interface ProductItem {
  modelYear?: number; make?: string; model?: string;
  [key: string]: unknown;
}

// ═══════════════════════════════════════════════════════════════════════
// RECALLS
// ═══════════════════════════════════════════════════════════════════════

/**
 * Search vehicle recalls by make, model, and model year.
 * All three parameters are required by the NHTSA API.
 *
 * Example:
 *   await getRecalls({ make: "tesla", model: "model 3", modelYear: 2024 });
 */
export async function getRecalls(opts: {
  make: string;
  model: string;
  modelYear: number;
}): Promise<Recall[]> {
  const res = await api.get<NhtsaResponse<Recall>>("/recalls/recallsByVehicle", {
    make: opts.make, model: opts.model, modelYear: String(opts.modelYear),
  });
  return extractResults(res);
}

/**
 * Get recall details by NHTSA campaign number.
 *
 * Example:
 *   await getRecallByCampaign("23V838000");
 */
export async function getRecallByCampaign(campaignNumber: string): Promise<Recall[]> {
  const res = await api.get<NhtsaResponse<Recall>>("/recalls/campaignNumber", { campaignNumber });
  return extractResults(res);
}

// ═══════════════════════════════════════════════════════════════════════
// COMPLAINTS
// ═══════════════════════════════════════════════════════════════════════

/**
 * Search vehicle complaints by make, model, and model year.
 * All three parameters are required by the NHTSA API.
 *
 * Example:
 *   await getComplaints({ make: "tesla", model: "model 3", modelYear: 2023 });
 */
export async function getComplaints(opts: {
  make: string;
  model: string;
  modelYear: number;
}): Promise<Complaint[]> {
  const res = await api.get<NhtsaResponse<Complaint>>("/complaints/complaintsByVehicle", {
    make: opts.make, model: opts.model, modelYear: String(opts.modelYear),
  });
  return extractResults(res);
}

/**
 * Get complaint details by ODI number.
 *
 * Example:
 *   await getComplaintByOdi(11184030);
 */
export async function getComplaintByOdi(odiNumber: number): Promise<Complaint | null> {
  const res = await api.get<NhtsaResponse<Complaint>>("/complaints/odinumber", { odinumber: String(odiNumber) });
  return extractResults(res)[0] ?? null;
}

// ═══════════════════════════════════════════════════════════════════════
// PRODUCT BROWSING (model years, makes, models)
// ═══════════════════════════════════════════════════════════════════════

/**
 * List available model years that have recalls or complaints.
 * issueType: 'r' for recalls, 'c' for complaints.
 *
 * Example:
 *   await getProductModelYears("r"); // years with recalls
 *   await getProductModelYears("c"); // years with complaints
 */
export async function getProductModelYears(issueType: "r" | "c"): Promise<ProductItem[]> {
  const res = await api.get<NhtsaResponse<ProductItem>>("/products/vehicle/modelYears", { issueType });
  return extractResults(res);
}

/**
 * List makes for a model year that have recalls or complaints.
 *
 * Example:
 *   await getProductMakes({ modelYear: 2024, issueType: "r" });
 */
export async function getProductMakes(opts: {
  modelYear: number;
  issueType: "r" | "c";
}): Promise<ProductItem[]> {
  const res = await api.get<NhtsaResponse<ProductItem>>("/products/vehicle/makes", {
    modelYear: String(opts.modelYear), issueType: opts.issueType,
  });
  return extractResults(res);
}

/**
 * List models for a make and year that have recalls or complaints.
 *
 * Example:
 *   await getProductModels({ modelYear: 2024, make: "tesla", issueType: "r" });
 */
export async function getProductModels(opts: {
  modelYear: number;
  make: string;
  issueType: "r" | "c";
}): Promise<ProductItem[]> {
  const res = await api.get<NhtsaResponse<ProductItem>>("/products/vehicle/models", {
    modelYear: String(opts.modelYear), make: opts.make, issueType: opts.issueType,
  });
  return extractResults(res);
}

// ═══════════════════════════════════════════════════════════════════════
// VIN DECODE
// ═══════════════════════════════════════════════════════════════════════

/**
 * Decode a VIN to get vehicle specifications.
 *
 * Example:
 *   await decodeVin("1HGCM82633A123456");
 */
export async function decodeVin(vin: string): Promise<VinResult> {
  const res = await vpicApi.get<{ Results?: VinResult[] }>(`/vehicles/DecodeVinValues/${encodeURIComponent(vin)}`, { format: "json" });
  return res?.Results?.[0] ?? {};
}

/**
 * Get all vehicle makes from the vPIC database.
 */
export async function getAllMakes(): Promise<Array<{ Make_ID: number; Make_Name: string }>> {
  const res = await vpicApi.get<{ Results?: Array<{ Make_ID: number; Make_Name: string }> }>("/vehicles/GetAllMakes", { format: "json" });
  return res?.Results ?? [];
}

/**
 * Get models for a specific make and optional year.
 */
export async function getModelsForMake(opts: {
  make: string;
  modelYear?: number;
}): Promise<Array<{ Make_ID: number; Make_Name: string; Model_ID: number; Model_Name: string }>> {
  const path = opts.modelYear
    ? `/vehicles/GetModelsForMakeYear/make/${encodeURIComponent(opts.make)}/modelyear/${opts.modelYear}`
    : `/vehicles/GetModelsForMake/${encodeURIComponent(opts.make)}`;
  const res = await vpicApi.get<{ Results?: Array<{ Make_ID: number; Make_Name: string; Model_ID: number; Model_Name: string }> }>(path, { format: "json" });
  return res?.Results ?? [];
}

// ═══════════════════════════════════════════════════════════════════════
// SAFETY RATINGS (NCAP 5-Star)
// ═══════════════════════════════════════════════════════════════════════

/**
 * Browse safety ratings — list model years, makes for a year, models for make+year,
 * or vehicle variants for make+model+year.
 *
 * Example:
 *   await getSafetyRatingVehicles({ modelYear: 2024, make: "Tesla", model: "Model 3" });
 */
export async function getSafetyRatingVehicles(opts: {
  make: string;
  model: string;
  modelYear: number;
}): Promise<SafetyRatingVehicle[]> {
  const res = await api.get<NhtsaResponse<SafetyRatingVehicle>>(
    `/SafetyRatings/modelyear/${opts.modelYear}/make/${encodeURIComponent(opts.make)}/model/${encodeURIComponent(opts.model)}`,
  );
  return extractResults(res);
}

/**
 * Get detailed safety ratings for a vehicle by VehicleId.
 *
 * Example:
 *   await getSafetyRatingDetail(19950);
 */
export async function getSafetyRatingDetail(vehicleId: number): Promise<SafetyRating | null> {
  const res = await api.get<NhtsaResponse<SafetyRating>>(`/SafetyRatings/VehicleId/${vehicleId}`);
  return extractResults(res)[0] ?? null;
}

// ═══════════════════════════════════════════════════════════════════════
// CAR SEAT INSPECTION STATIONS
// ═══════════════════════════════════════════════════════════════════════

/**
 * Find car seat inspection stations by ZIP code, state, or geo coordinates.
 *
 * Example:
 *   await getCarSeatStations({ state: "CA" });
 *   await getCarSeatStations({ zip: "90210" });
 *   await getCarSeatStations({ lat: 30.1783, long: -96.3911, miles: 50 });
 */
export async function getCarSeatStations(opts: {
  zip?: string;
  state?: string;
  lat?: number;
  long?: number;
  miles?: number;
}): Promise<CssiStation[]> {
  let path: string;
  if (opts.zip) {
    path = `/CSSIStation/zip/${opts.zip}`;
  } else if (opts.state) {
    path = `/CSSIStation/state/${opts.state.toUpperCase()}`;
  } else if (opts.lat != null && opts.long != null) {
    const res = await api.get<NhtsaResponse<CssiStation>>("/CSSIStation", {
      lat: String(opts.lat), long: String(opts.long), miles: String(opts.miles ?? 25),
    });
    return extractResults(res);
  } else {
    throw new Error("Provide zip, state, or lat+long");
  }
  const res = await api.get<NhtsaResponse<CssiStation>>(path);
  return extractResults(res);
}

/** Clear both NHTSA caches. */
export function clearCache(): void {
  api.clearCache();
  vpicApi.clearCache();
}
