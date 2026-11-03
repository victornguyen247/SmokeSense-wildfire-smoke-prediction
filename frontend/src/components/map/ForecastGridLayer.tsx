import { useEffect } from "react";
import type { ExpressionSpecification } from "maplibre-gl";

import type { AqiCategoryInfo, GridCellCollection, GridForecast } from "../../api/models";
import { useMap } from "../../context/MapContext";
import { categoryColorExpression } from "../../utils/aqi";
import { firstSymbolLayerId, removeFromMap } from "../../utils/map";

const SOURCE_ID = "forecast-grid";
const FILL_LAYER_ID = "forecast-grid-fill";
const LOW_CONFIDENCE_LAYER_ID = "forecast-grid-low-confidence";

type GridHorizon = GridForecast["horizons"][number];

type ForecastGridLayerProps = {
  cells: GridCellCollection;
  /** The selected horizon's cell values; undefined draws every cell as "no data". */
  horizon: GridHorizon | undefined;
  categories: AqiCategoryInfo[];
  /** `/meta` `low_confidence_dist_km`: cells farther than this from a monitor are drawn faded. */
  lowConfidenceDistKm: number;
};

const hasValue: ExpressionSpecification = ["!=", ["coalesce", ["feature-state", "aqi"], ""], ""];
const isLowConfidence: ExpressionSpecification = ["boolean", ["feature-state", "low"], false];

/**
 * The grid forecast: one polygon per GEO-02 cell, colored by its AQI category at the
 * selected horizon. The polygons are added once; switching horizon only changes each
 * cell's feature state, so it is instant (docs/api.md, "/grid/cells and /forecast/grid").
 */
export function ForecastGridLayer({
  cells,
  horizon,
  categories,
  lowConfidenceDistKm,
}: ForecastGridLayerProps) {
  const map = useMap();

  // Geometry and styling: once per grid (and legend).
  useEffect(() => {
    if (!map) return;
    map.addSource(SOURCE_ID, { type: "geojson", data: cells, promoteId: "id" });
    const beforeId = firstSymbolLayerId(map);
    map.addLayer(
      {
        id: FILL_LAYER_ID,
        type: "fill",
        source: SOURCE_ID,
        paint: {
          "fill-color": categoryColorExpression(categories, ["feature-state", "aqi"]),
          "fill-opacity": ["case", ["!", hasValue], 0.18, isLowConfidence, 0.3, 0.6],
          "fill-outline-color": "rgba(0, 0, 0, 0)",
        },
      },
      beforeId,
    );
    // Lower confidence is a dashed outline as well as a fainter fill, so it doesn't rely
    // on telling two shades of one color apart.
    map.addLayer(
      {
        id: LOW_CONFIDENCE_LAYER_ID,
        type: "line",
        source: SOURCE_ID,
        paint: {
          "line-color": "#3c4043",
          "line-width": 1,
          "line-dasharray": [2, 2],
          "line-opacity": ["case", ["all", hasValue, isLowConfidence], 0.7, 0],
        },
      },
      beforeId,
    );
    return () => removeFromMap(map, [LOW_CONFIDENCE_LAYER_ID, FILL_LAYER_ID], [SOURCE_ID]);
  }, [map, cells, categories]);

  // Values: on every horizon (or forecast) change.
  useEffect(() => {
    if (!map) return;
    map.removeFeatureState({ source: SOURCE_ID });
    for (const cell of horizon?.cells ?? []) {
      map.setFeatureState(
        { source: SOURCE_ID, id: cell.id },
        { aqi: cell.aqi_category, low: cell.nearest_monitor_dist_km > lowConfidenceDistKm },
      );
    }
    // `cells` and `categories` re-add the source, which drops feature state, so they
    // are dependencies here too.
  }, [map, cells, categories, horizon, lowConfidenceDistKm]);

  return null;
}
