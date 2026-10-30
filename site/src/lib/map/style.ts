import type { LayerSpecification, StyleSpecification } from "maplibre-gl";
import positron from "$lib/utils/basemap/positron.json";
import { LAYERS } from "$lib/layers";

function layersFor(id: string, kind: "polygon" | "line", color: string, visible: boolean): LayerSpecification[] {
  const visibility = visible ? "visible" : "none";
  const line: LayerSpecification = {
    id: `${id}-line`,
    type: "line",
    source: id,
    "source-layer": id,
    layout: { visibility },
    paint: { "line-color": color, "line-width": 1.5 },
  };
  if (kind === "line") return [line];
  return [
    {
      id: `${id}-fill`,
      type: "fill",
      source: id,
      "source-layer": id,
      layout: { visibility },
      paint: { "fill-color": color, "fill-opacity": 0.08 },
    },
    line,
  ];
}

export function buildStyle(tilesBase: string): StyleSpecification {
  return {
    version: 8,
    sprite: positron.sprite,
    glyphs: positron.glyphs,
    sources: {
      ...(positron.sources as StyleSpecification["sources"]),
      ...Object.fromEntries(
        LAYERS.map((l) => [l.id, { type: "vector" as const, url: `pmtiles://${tilesBase}/${l.id}.pmtiles` }]),
      ),
    },
    layers: [
      ...(positron.layers as LayerSpecification[]),
      ...LAYERS.flatMap((l) => layersFor(l.id, l.kind, l.color, l.visible)),
    ],
  };
}
