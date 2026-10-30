// Column groups for attributes.json from pipeline/attributes.py; each column is `${group}_${source}`.
export const SOURCES: Record<string, string> = {
  gaul: "GAUL",
  ungeodata: "UN Geodata",
  fieldmaps: "fieldmaps",
  wp: "World Polygons",
  unterm: "UNTERM",
  m49: "M49",
};

export interface AttributeGroup {
  key: string;
  label: string;
  sources: string[];
  compare: boolean;
}

// Status and region use different vocabularies per source, so only a source pair compares them.
export const GROUPS: AttributeGroup[] = [
  { key: "name", label: "Name", sources: ["gaul", "ungeodata", "fieldmaps", "wp", "unterm", "m49"], compare: true },
  { key: "mapcode", label: "Map code", sources: ["gaul"], compare: false },
  { key: "sovereign", label: "Sovereign", sources: ["ungeodata", "fieldmaps"], compare: true },
  { key: "status", label: "Status", sources: ["ungeodata", "fieldmaps", "wp", "unterm"], compare: false },
  { key: "region", label: "Region", sources: ["gaul", "ungeodata", "fieldmaps", "m49"], compare: false },
];

// Sources that publish their own entity list, as opposed to M49 which shares the ref table with UNTERM.
const ENTITY_SOURCES = ["gaul", "ungeodata", "fieldmaps", "wp", "unterm"];

export const DIFF_TYPES = {
  any: "Any difference",
  differs: "Value differs",
  missing: "Missing from a source",
  several: "Several features under one code",
  only: "Code in only one source",
  none: "No differences",
  all: "All rows",
} as const;
export type DiffType = keyof typeof DIFF_TYPES;
type DiffKind = "differs" | "missing" | "several" | "only";

export interface Lens {
  group: string;
  diff: DiffType;
  pair: string;
  status: string;
  region: string;
  sovereign: string;
  query: string;
}

export type AttributeRow = Record<string, string | number | null>;

export function value(row: AttributeRow, group: string, source: string): string {
  return String(row[`${group}_${source}`] ?? "").trim();
}

// Facets take the UN view first and fall back to fieldmaps, which follows it.
export const FACETS = {
  status: { label: "Status (UN Geodata)", get: (r: AttributeRow) => value(r, "status", "ungeodata") || value(r, "status", "fieldmaps") },
  region: { label: "Region (M49)", get: (r: AttributeRow) => value(r, "region", "m49") || value(r, "region", "fieldmaps") },
  sovereign: { label: "Sovereign (UN Geodata)", get: (r: AttributeRow) => value(r, "sovereign", "ungeodata") || value(r, "sovereign", "fieldmaps") },
} as const;
export type Facet = keyof typeof FACETS;
export const NONE = "(none)";

export function groupsInScope(lens: Lens): AttributeGroup[] {
  return lens.group ? GROUPS.filter((g) => g.key === lens.group) : GROUPS;
}

export function sourcesFor(group: AttributeGroup, lens: Lens): string[] {
  return lens.pair ? group.sources.filter((s) => s === "gaul" || s === lens.pair) : group.sources;
}

export const TIE = Symbol("tie");

// The most common non-empty value in a group, TIE when the top values are level, or null when all agree.
export function majority(
  row: AttributeRow,
  group: AttributeGroup,
  sources = group.sources,
): string | typeof TIE | null {
  const counts = new Map<string, number>();
  for (const s of sources) {
    const v = value(row, group.key, s);
    if (v) counts.set(v, (counts.get(v) ?? 0) + 1);
  }
  if (counts.size < 2) return null;
  const [first, second] = [...counts].sort((a, b) => b[1] - a[1]);
  return first[1] === second[1] ? TIE : first[0];
}

function diffKinds(row: AttributeRow, lens: Lens): Set<DiffKind> {
  const kinds = new Set<DiffKind>();
  const scoped = new Set<string>();
  for (const group of groupsInScope(lens)) {
    const sources = sourcesFor(group, lens);
    sources.forEach((s) => scoped.add(s));
    if (sources.length < 2) continue;
    const present = sources.map((s) => value(row, group.key, s)).filter(Boolean);
    if (present.length > 0 && present.length < sources.length) kinds.add("missing");
    if ((lens.pair || group.compare) && new Set(present).size > 1) kinds.add("differs");
  }
  if ([...scoped].some((s) => Number(row[`count_${s}`] ?? 0) > 1)) kinds.add("several");
  const entities = ENTITY_SOURCES.filter((s) => scoped.has(s));
  if (entities.length > 1 && entities.filter((s) => Number(row[`count_${s}`] ?? 0) > 0).length === 1) {
    kinds.add("only");
  }
  return kinds;
}

// Rows are loaded once and never mutated, so per-row derived values are cached for the option counts.
interface RowCache {
  haystack: string;
  facets: Record<Facet, string>;
  kinds: Map<string, Set<DiffKind>>;
}
const cache = new WeakMap<AttributeRow, RowCache>();

function cached(row: AttributeRow): RowCache {
  let c = cache.get(row);
  if (!c) {
    c = {
      haystack: Object.values(row)
        .map((v) => String(v ?? "").toLowerCase())
        .join("\n"),
      facets: Object.fromEntries(
        (Object.keys(FACETS) as Facet[]).map((f) => [f, FACETS[f].get(row) || NONE]),
      ) as Record<Facet, string>,
      kinds: new Map(),
    };
    cache.set(row, c);
  }
  return c;
}

export function matches(row: AttributeRow, lens: Lens): boolean {
  const c = cached(row);
  for (const facet of Object.keys(FACETS) as Facet[]) {
    if (lens[facet] && c.facets[facet] !== lens[facet]) return false;
  }
  if (lens.diff !== "all") {
    const key = `${lens.group}|${lens.pair}`;
    let kinds = c.kinds.get(key);
    if (!kinds) c.kinds.set(key, (kinds = diffKinds(row, lens)));
    if (lens.diff === "any" ? kinds.size === 0 : lens.diff === "none" ? kinds.size > 0 : !kinds.has(lens.diff)) {
      return false;
    }
  }
  const q = lens.query.trim().toLowerCase();
  return !q || c.haystack.includes(q);
}
