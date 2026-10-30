// One entry per PMTiles file from pipeline/tiles.py; the source-layer name is the id.
export interface SourceLayer {
  id: string;
  label: string;
  group: string;
  kind: "polygon" | "line";
  color: string;
  visible: boolean;
}

export const LAYERS: SourceLayer[] = [
  { id: "gaul_l0", label: "GAUL 2025 L0", group: "FAO", kind: "polygon", color: "#009EDB", visible: true },
  { id: "ungeodata_polygons", label: "UN Geodata polygons", group: "UN Geodata 1M", kind: "polygon", color: "#CF3F0B", visible: true },
  { id: "ungeodata_lines", label: "UN Geodata lines", group: "UN Geodata 1M", kind: "line", color: "#CF3F0B", visible: false },
  { id: "fieldmaps_wp_polygons", label: "fieldmaps polygons (WP land)", group: "fieldmaps", kind: "polygon", color: "#27833A", visible: false },
  { id: "fieldmaps_wp_lines", label: "fieldmaps lines (WP land)", group: "fieldmaps", kind: "line", color: "#27833A", visible: false },
  { id: "fieldmaps_osm_polygons", label: "fieldmaps polygons (OSM land)", group: "fieldmaps", kind: "polygon", color: "#733D96", visible: false },
  { id: "fieldmaps_osm_lines", label: "fieldmaps lines (OSM land)", group: "fieldmaps", kind: "line", color: "#733D96", visible: false },
  { id: "wp_polygons", label: "World Polygons", group: "US State Dept", kind: "polygon", color: "#7C7067", visible: false },
  { id: "lsib_lines", label: "LSIB lines", group: "US State Dept", kind: "line", color: "#262626", visible: false },
];
