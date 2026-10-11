/**
 * nhtsa MCP tools — vehicle recalls, complaints, safety ratings, VIN decode, car seat stations.
 *
 * Docs: https://www.nhtsa.gov/nhtsa-datasets-and-apis
 */

import { z } from "zod";
import type { Tool } from "fastmcp";
import {
  getRecalls, getRecallByCampaign,
  getComplaints, getComplaintByOdi,
  getProductModelYears, getProductMakes, getProductModels,
  decodeVin, getModelsForMake,
  getSafetyRatingVehicles, getSafetyRatingDetail,
  getCarSeatStations,
} from "./sdk.js";
import { tableResponse, listResponse, recordResponse, emptyResponse } from "../../shared/response.js";

export const tools: Tool<any, any>[] = [
  // ── Recalls ──────────────────────────────────────────────────────
  {
    name: "nhtsa_recalls",
    description:
      "Search NHTSA vehicle recalls by make, model, and model year.\n" +
      "All three parameters are required by the NHTSA API.\n" +
      "Use nhtsa_models to find valid models for a make, or nhtsa_recall_detail for a specific campaign.\n\n" +
      "Example: make='tesla', model='model 3', model_year=2024",
    annotations: { title: "NHTSA: Vehicle Recalls", readOnlyHint: true },
    parameters: z.object({
      make: z.string().describe("Vehicle make: 'toyota', 'ford', 'tesla', 'honda'"),
      model: z.string().describe("Vehicle model: 'camry', 'f-150', 'model 3', 'civic'"),
      model_year: z.number().int().describe("Model year: 2020, 2023, 2024"),
    }),
    execute: async ({ make, model, model_year }) => {
      const data = await getRecalls({ make, model, modelYear: model_year });
      if (!data.length) return emptyResponse(`No recalls found for ${model_year} ${make} ${model}.`);
      return listResponse(
        `NHTSA recalls: ${data.length} for ${model_year} ${make} ${model}`,
        {
          total: data.length,
          items: data.map(r => ({
            campaignNumber: r.NHTSACampaignNumber, manufacturer: r.Manufacturer,
            component: r.Component, summary: r.Summary?.substring(0, 300),
            consequence: r.Consequence?.substring(0, 200),
            remedy: r.Remedy?.substring(0, 200),
            reportDate: r.ReportReceivedDate, parkIt: r.parkIt,
          })),
        },
      );
    },
  },

  {
    name: "nhtsa_recall_detail",
    description:
      "Get recall details by NHTSA campaign number.\n" +
      "Campaign numbers look like '23V838000' or '12V176000'.\n" +
      "Returns full recall information including affected vehicles, summary, consequence, and remedy.",
    annotations: { title: "NHTSA: Recall by Campaign Number", readOnlyHint: true },
    parameters: z.object({
      campaign_number: z.string().describe("NHTSA campaign number (e.g. '23V838000', '12V176000')"),
    }),
    execute: async ({ campaign_number }) => {
      const data = await getRecallByCampaign(campaign_number);
      if (!data.length) return emptyResponse(`No recall found for campaign ${campaign_number}.`);
      return listResponse(
        `NHTSA recall campaign ${campaign_number}: ${data.length} affected vehicles`,
        {
          total: data.length,
          items: data.map(r => ({
            campaignNumber: r.NHTSACampaignNumber, manufacturer: r.Manufacturer,
            make: r.Make, model: r.Model, modelYear: r.ModelYear,
            component: r.Component, summary: r.Summary,
            consequence: r.Consequence, remedy: r.Remedy,
            reportDate: r.ReportReceivedDate, parkIt: r.parkIt,
          })),
        },
      );
    },
  },

  // ── Complaints ───────────────────────────────────────────────────
  {
    name: "nhtsa_complaints",
    description:
      "Search NHTSA vehicle complaints by make, model, and model year.\n" +
      "All three parameters are required by the NHTSA API.\n" +
      "Use nhtsa_models to find valid models for a make.\n\n" +
      "Example: make='tesla', model='model 3', model_year=2023",
    annotations: { title: "NHTSA: Vehicle Complaints", readOnlyHint: true },
    parameters: z.object({
      make: z.string().describe("Vehicle make: 'toyota', 'ford', 'tesla'"),
      model: z.string().describe("Vehicle model: 'camry', 'f-150', 'model 3'"),
      model_year: z.number().int().describe("Model year"),
    }),
    execute: async ({ make, model, model_year }) => {
      const data = await getComplaints({ make, model, modelYear: model_year });
      if (!data.length) return emptyResponse(`No complaints found for ${model_year} ${make} ${model}.`);
      return listResponse(
        `NHTSA complaints: ${data.length} for ${model_year} ${make} ${model}`,
        {
          total: data.length,
          items: data.slice(0, 30).map(c => ({
            odiNumber: c.odiNumber, dateOfIncident: c.dateOfIncident, dateFiled: c.dateComplaintFiled,
            crash: c.crash, fire: c.fire, injuries: c.numberOfInjuries, deaths: c.numberOfDeaths,
            components: c.components, summary: c.summary?.substring(0, 300),
          })),
        },
      );
    },
  },

  {
    name: "nhtsa_complaint_detail",
    description:
      "Get a specific complaint by its ODI number.\n" +
      "ODI numbers are in complaint search results (e.g. 11184030).",
    annotations: { title: "NHTSA: Complaint by ODI Number", readOnlyHint: true },
    parameters: z.object({
      odi_number: z.number().int().describe("ODI complaint number (e.g. 11184030)"),
    }),
    execute: async ({ odi_number }) => {
      const data = await getComplaintByOdi(odi_number);
      if (!data) return emptyResponse(`No complaint found for ODI ${odi_number}.`);
      return recordResponse(`NHTSA complaint ODI #${odi_number}`, data as Record<string, unknown>);
    },
  },

  // ── Product Browsing ─────────────────────────────────────────────
  {
    name: "nhtsa_model_years",
    description:
      "List model years that have recalls or complaints in the NHTSA database.\n" +
      "Use issue_type='r' for recalls (1949–present), 'c' for complaints.\n" +
      "Useful for discovering available data before querying.",
    annotations: { title: "NHTSA: Available Model Years", readOnlyHint: true },
    parameters: z.object({
      issue_type: z.enum(["r", "c"]).describe("'r' for recalls, 'c' for complaints"),
    }),
    execute: async ({ issue_type }) => {
      const data = await getProductModelYears(issue_type);
      if (!data.length) return emptyResponse("No model years found.");
      return tableResponse(
        `NHTSA model years (${issue_type === "r" ? "recalls" : "complaints"}): ${data.length} years`,
        { rows: data as Record<string, unknown>[] },
      );
    },
  },

  {
    name: "nhtsa_makes",
    description:
      "List vehicle makes for a model year that have recalls or complaints.\n" +
      "Use issue_type='r' for recalls, 'c' for complaints.\n\n" +
      "Example: model_year=2024, issue_type='r'",
    annotations: { title: "NHTSA: Makes for Model Year", readOnlyHint: true },
    parameters: z.object({
      model_year: z.number().int().describe("Model year"),
      issue_type: z.enum(["r", "c"]).describe("'r' for recalls, 'c' for complaints"),
    }),
    execute: async ({ model_year, issue_type }) => {
      const data = await getProductMakes({ modelYear: model_year, issueType: issue_type });
      if (!data.length) return emptyResponse(`No makes with ${issue_type === "r" ? "recalls" : "complaints"} for ${model_year}.`);
      return tableResponse(
        `NHTSA makes for ${model_year} (${issue_type === "r" ? "recalls" : "complaints"}): ${data.length}`,
        { rows: data as Record<string, unknown>[] },
      );
    },
  },

  {
    name: "nhtsa_models",
    description:
      "List vehicle models for a make and year that have recalls or complaints.\n" +
      "Or list all models for a make from the vPIC database (omit issue_type).\n\n" +
      "Example: make='tesla', model_year=2024, issue_type='r'",
    annotations: { title: "NHTSA: Models for Make", readOnlyHint: true },
    parameters: z.object({
      make: z.string().describe("Vehicle make: 'toyota', 'ford', 'tesla'"),
      model_year: z.number().int().optional().describe("Model year (optional for vPIC lookup)"),
      issue_type: z.enum(["r", "c"]).optional().describe("'r' for recalls, 'c' for complaints. Omit for general model list."),
    }),
    execute: async ({ make, model_year, issue_type }) => {
      if (issue_type && model_year) {
        const data = await getProductModels({ modelYear: model_year, make, issueType: issue_type });
        if (!data.length) return emptyResponse(`No ${make} models with ${issue_type === "r" ? "recalls" : "complaints"} for ${model_year}.`);
        return tableResponse(
          `NHTSA ${make} models for ${model_year} (${issue_type === "r" ? "recalls" : "complaints"}): ${data.length}`,
          { rows: data as Record<string, unknown>[] },
        );
      }
      const data = await getModelsForMake({ make, modelYear: model_year });
      if (!data.length) return emptyResponse(`No models found for ${make}.`);
      return tableResponse(
        `${make} models${model_year ? ` (${model_year})` : ""}: ${data.length}`,
        { rows: data as Record<string, unknown>[] },
      );
    },
  },

  // ── VIN Decode ───────────────────────────────────────────────────
  {
    name: "nhtsa_decode_vin",
    description:
      "Decode a Vehicle Identification Number (VIN) to get specifications.\n" +
      "Returns make, model, year, engine, body class, drive type, plant info.\n" +
      "VINs are 17 characters.",
    annotations: { title: "NHTSA: VIN Decode", readOnlyHint: true },
    parameters: z.object({
      vin: z.string().min(11).max(17).describe("Vehicle Identification Number (17 characters)"),
    }),
    execute: async ({ vin }) => {
      const data = await decodeVin(vin);
      if (!data || data.ErrorCode === "0") return emptyResponse(`Could not decode VIN: ${vin}`);
      return recordResponse(`VIN ${vin}`, {
        make: data.Make, model: data.Model, year: data.ModelYear,
        manufacturer: data.Manufacturer, vehicleType: data.VehicleType,
        bodyClass: data.BodyClass, driveType: data.DriveType,
        fuelType: data.FuelTypePrimary, engine: data.EngineModel,
        cylinders: data.EngineCylinders, displacement: data.DisplacementL,
        transmission: data.TransmissionStyle,
        plantCity: data.PlantCity, plantCountry: data.PlantCountry,
      });
    },
  },

  // ── Safety Ratings ───────────────────────────────────────────────
  {
    name: "nhtsa_safety_ratings",
    description:
      "Search NHTSA 5-star safety ratings (NCAP) by make, model, and year.\n" +
      "Returns vehicle variants with VehicleId. Use the VehicleId with nhtsa_safety_rating_detail.\n\n" +
      "Ratings: 5 stars = highest, 1 star = lowest. Data from 1990 to present.",
    annotations: { title: "NHTSA: Safety Ratings Search", readOnlyHint: true },
    parameters: z.object({
      make: z.string().describe("Vehicle make: 'honda', 'toyota', 'ford'"),
      model: z.string().describe("Vehicle model: 'civic', 'camry', 'f-150'"),
      model_year: z.number().int().describe("Model year"),
    }),
    execute: async ({ make, model, model_year }) => {
      const vehicles = await getSafetyRatingVehicles({ make, model, modelYear: model_year });
      if (!vehicles.length) return emptyResponse(`No safety ratings for ${model_year} ${make} ${model}.`);
      return tableResponse(
        `NHTSA safety rated variants: ${vehicles.length} for ${model_year} ${make} ${model}`,
        { rows: vehicles as Record<string, unknown>[] },
      );
    },
  },

  {
    name: "nhtsa_safety_rating_detail",
    description:
      "Get detailed NHTSA 5-star safety ratings for a specific vehicle variant.\n" +
      "Requires a VehicleId from nhtsa_safety_ratings search results.\n" +
      "Returns crash test ratings, rollover risk, and safety technology assessments.",
    annotations: { title: "NHTSA: Safety Rating Detail", readOnlyHint: true },
    parameters: z.object({
      vehicle_id: z.number().int().describe("VehicleId from safety ratings search (e.g. 19950)"),
    }),
    execute: async ({ vehicle_id }) => {
      const data = await getSafetyRatingDetail(vehicle_id);
      if (!data) return emptyResponse(`No safety rating found for VehicleId ${vehicle_id}.`);
      return recordResponse(
        `Safety rating: ${data.VehicleDescription ?? `VehicleId ${vehicle_id}`}`,
        {
          overallRating: data.OverallRating,
          frontCrash: data.OverallFrontCrashRating,
          frontCrashDriver: data.FrontCrashDriversideRating,
          frontCrashPassenger: data.FrontCrashPassengersideRating,
          sideCrash: data.OverallSideCrashRating,
          sideCrashDriver: data.SideCrashDriversideRating,
          sideCrashPassenger: data.SideCrashPassengersideRating,
          rollover: data.RolloverRating,
          rolloverRisk: data.RolloverPossibility,
          electronicStabilityControl: data.NHTSAElectronicStabilityControl,
          forwardCollisionWarning: data.NHTSAForwardCollisionWarning,
          laneDepartureWarning: data.NHTSALaneDepartureWarning,
          complaintsCount: data.ComplaintsCount,
          recallsCount: data.RecallsCount,
          investigationsCount: data.InvestigationCount,
        },
      );
    },
  },

  // ── Car Seat Inspection Stations ─────────────────────────────────
  {
    name: "nhtsa_car_seat_stations",
    description:
      "Find car seat inspection stations near a location.\n" +
      "Search by ZIP code, state, or geographic coordinates.\n" +
      "Car seat inspection stations help parents verify proper installation.\n\n" +
      "Example: state='CA', or zip='90210', or lat=30.18 + long=-96.39 + miles=50",
    annotations: { title: "NHTSA: Car Seat Inspection Stations", readOnlyHint: true },
    parameters: z.object({
      zip: z.string().optional().describe("ZIP code (e.g. '90210')"),
      state: z.string().max(2).optional().describe("Two-letter state code (e.g. 'CA', 'TX')"),
      lat: z.number().optional().describe("Latitude for geo search"),
      long: z.number().optional().describe("Longitude for geo search"),
      miles: z.number().optional().describe("Search radius in miles (default 25, used with lat/long)"),
    }),
    execute: async ({ zip, state, lat, long: lng, miles }) => {
      const data = await getCarSeatStations({ zip, state, lat, long: lng, miles });
      if (!data.length) return emptyResponse("No car seat inspection stations found for this location.");
      return listResponse(
        `Car seat inspection stations: ${data.length} found`,
        {
          total: data.length,
          items: data.slice(0, 50).map(s => ({
            name: s.name, address: s.address, city: s.city,
            state: s.state, zip: s.zip, phone: s.phone,
          })),
        },
      );
    },
  },
];
