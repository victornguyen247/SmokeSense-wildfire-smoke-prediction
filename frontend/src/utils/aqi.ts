// AQI display helpers. Colors, labels and ranges always come from `/meta`
// `aqi_categories` (CLAUDE.md rule 4); nothing here knows a threshold.

import type { ExpressionSpecification } from "maplibre-gl";

import type { AqiCategory, AqiCategoryInfo } from "../api/models";

/** Fill for a cell or point with no forecast. Not an AQI color, so it can't be mistaken for one. */
export const NO_DATA_COLOR = "#9AA0A6";

/** The `/meta` entry for a category key. */
export function categoryInfo(
  categories: AqiCategoryInfo[],
  key: AqiCategory,
): AqiCategoryInfo | undefined {
  return categories.find((c) => c.key === key);
}

/** "35.5–55.4 µg/m³", or "≥ 225.5 µg/m³" for the top category. */
export function formatRange(category: AqiCategoryInfo): string {
  return category.pm25_max === null
    ? `≥ ${category.pm25_min} µg/m³`
    : `${category.pm25_min}–${category.pm25_max} µg/m³`;
}

/** "42.3 µg/m³". `pm25` arrives truncated to 0.1. */
export function formatPm25(pm25: number): string {
  return `${pm25.toFixed(1)} µg/m³`;
}

/**
 * A MapLibre color expression: the category key in `input` → its `/meta` color, and
 * NO_DATA_COLOR for anything else (including no value).
 */
export function categoryColorExpression(
  categories: AqiCategoryInfo[],
  input: ExpressionSpecification,
): ExpressionSpecification {
  const pairs = categories.flatMap((c) => [c.key, c.color]);
  // The spec type can't express a variable number of match pairs, hence the cast.
  return ["match", ["coalesce", input, ""], ...pairs, NO_DATA_COLOR] as unknown as ExpressionSpecification;
}
