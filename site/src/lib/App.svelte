<script lang="ts">
  import "maplibre-gl/dist/maplibre-gl.css";
  import * as maplibregl from "maplibre-gl";
  import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
  import { Protocol } from "pmtiles";
  import AttributesTable from "$lib/AttributesTable.svelte";
  import { LAYERS } from "$lib/layers";
  import { buildStyle } from "$lib/map/style";
  import { unlock } from "$lib/unlock";
  import { MAP_DISCLAIMER } from "$lib/utils/mapDisclaimer";

  const STORAGE_KEY = "adm0-site-password";

  maplibregl.setWorkerUrl(workerUrl);

  interface Hit {
    layerId: string;
    label: string;
    color: string;
    properties: Record<string, unknown>;
  }

  let tilesBase = $state<string | null>(null);
  let password = $state("");
  let error = $state(false);
  let visible = $state(Object.fromEntries(LAYERS.map((l) => [l.id, l.visible])));
  let hits = $state<Hit[]>([]);
  let container = $state<HTMLDivElement>();
  let tab = $state<"map" | "table">("map");
  let map: maplibregl.Map | null = null;

  async function tryUnlock(value: string, remember: boolean) {
    const url = await unlock(value);
    if (url) {
      if (remember) sessionStorage.setItem(STORAGE_KEY, value);
      tilesBase = url;
    }
    return url !== null;
  }

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    error = !(await tryUnlock(password, true));
  }

  $effect(() => {
    const saved = sessionStorage.getItem(STORAGE_KEY);
    if (saved) tryUnlock(saved, false);
  });

  $effect(() => {
    if (!tilesBase || !container) return;
    const protocol = new Protocol();
    maplibregl.addProtocol("pmtiles", protocol.tile);
    const m = new maplibregl.Map({
      container,
      style: buildStyle(tilesBase),
      center: [20, 10],
      zoom: 2,
      hash: true,
      attributionControl: { compact: true, customAttribution: MAP_DISCLAIMER },
    });
    m.addControl(new maplibregl.NavigationControl(), "top-right");
    m.on("click", (e) => {
      const ids = LAYERS.filter((l) => visible[l.id]).flatMap((l) =>
        l.kind === "polygon" ? [`${l.id}-fill`] : [`${l.id}-line`],
      );
      const pad = 3;
      const features = m.queryRenderedFeatures(
        [
          [e.point.x - pad, e.point.y - pad],
          [e.point.x + pad, e.point.y + pad],
        ],
        { layers: ids },
      );
      const seen = new Set<string>();
      hits = features.flatMap((f) => {
        const layer = LAYERS.find((l) => l.id === f.sourceLayer);
        const key = `${f.sourceLayer}:${JSON.stringify(f.properties)}`;
        if (!layer || seen.has(key)) return [];
        seen.add(key);
        return [{ layerId: layer.id, label: layer.label, color: layer.color, properties: f.properties }];
      });
    });
    map = m;
    return () => {
      m.remove();
      map = null;
      maplibregl.removeProtocol("pmtiles");
    };
  });

  function show(next: "map" | "table") {
    tab = next;
    if (next === "map") requestAnimationFrame(() => map?.resize());
  }

  function toggle(id: string) {
    visible[id] = !visible[id];
    const layer = LAYERS.find((l) => l.id === id);
    if (!map || !layer) return;
    for (const suffix of layer.kind === "polygon" ? ["fill", "line"] : ["line"]) {
      map.setLayoutProperty(`${id}-${suffix}`, "visibility", visible[id] ? "visible" : "none");
    }
  }

  const groups = [...new Set(LAYERS.map((l) => l.group))];
</script>

{#if !tilesBase}
  <form class="gate" onsubmit={submit}>
    <label>
      Password
      <!-- svelte-ignore a11y_autofocus -->
      <input type="password" bind:value={password} autofocus />
    </label>
    <button type="submit">Open</button>
    {#if error}<p class="error">Incorrect password.</p>{/if}
  </form>
{:else}
  <div class="app">
    <nav>
      <button class:active={tab === "map"} onclick={() => show("map")}>Map</button>
      <button class:active={tab === "table"} onclick={() => show("table")}>Names and attributes</button>
    </nav>
    <div class="view" class:hidden={tab !== "map"}>
    <aside>
      {#each groups as group (group)}
        <h2>{group}</h2>
        {#each LAYERS.filter((l) => l.group === group) as layer (layer.id)}
          <label class="layer">
            <input type="checkbox" checked={visible[layer.id]} onchange={() => toggle(layer.id)} />
            <span class="swatch {layer.kind}" style:--color={layer.color}></span>
            {layer.label}
          </label>
        {/each}
      {/each}
      <h2>At this point</h2>
      {#if hits.length === 0}
        <p class="hint">Click the map to compare what each visible source says here.</p>
      {/if}
      {#each hits as hit, i (i)}
        <section class="hit">
          <h3><span class="swatch" style:--color={hit.color}></span>{hit.label}</h3>
          <table>
            <tbody>
              {#each Object.entries(hit.properties) as [key, value] (key)}
                <tr><th>{key}</th><td>{value}</td></tr>
              {/each}
            </tbody>
          </table>
        </section>
      {/each}
    </aside>
    <div class="map" bind:this={container}></div>
    </div>
    {#if tab === "table"}
      <div class="view"><AttributesTable {tilesBase} /></div>
    {/if}
  </div>
{/if}

<style>
  .gate {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    width: 18rem;
    margin: 20vh auto;
  }
  .gate label {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }
  .gate input,
  .gate button {
    padding: 0.5rem;
    font-size: 1rem;
  }
  .gate button {
    background: var(--cd-ocha-blue);
    color: var(--cd-white, #fff);
    border: 0;
    cursor: pointer;
  }
  .error {
    color: var(--cd-red--aa);
    margin: 0;
  }
  .app {
    display: flex;
    flex-direction: column;
    height: 100vh;
  }
  nav {
    display: flex;
    border-bottom: 1px solid var(--cd-grey--400);
  }
  nav button {
    padding: 0.6rem 1rem;
    border: 0;
    border-bottom: 3px solid transparent;
    background: none;
    font-size: 0.875rem;
    cursor: pointer;
  }
  nav button.active {
    border-bottom-color: var(--cd-ocha-blue);
    font-weight: 600;
  }
  .view {
    display: flex;
    flex: 1;
    min-height: 0;
  }
  .view > :global(.table-view) {
    flex: 1;
    min-width: 0;
  }
  .hidden {
    display: none;
  }
  aside {
    width: 22rem;
    overflow-y: auto;
    padding: 1rem;
    border-right: 1px solid var(--cd-grey--400);
    font-size: 0.875rem;
  }
  h2 {
    font-size: 0.75rem;
    text-transform: uppercase;
    color: var(--cd-grey--700);
    margin: 1rem 0 0.25rem;
  }
  .layer {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.15rem 0;
    cursor: pointer;
  }
  .swatch {
    display: inline-block;
    width: 0.9rem;
    height: 0.9rem;
    margin-right: 0.3rem;
    border: 2px solid var(--color);
    background: color-mix(in srgb, var(--color) 15%, transparent);
    vertical-align: middle;
  }
  .swatch.line {
    height: 0;
    border-width: 2px 0 0;
  }
  .hint {
    color: var(--cd-grey--700);
  }
  .hit h3 {
    font-size: 0.875rem;
    margin: 0.75rem 0 0.25rem;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.75rem;
  }
  th,
  td {
    text-align: left;
    vertical-align: top;
    padding: 0.15rem 0.3rem;
    border-bottom: 1px solid var(--cd-grey--300);
    word-break: break-word;
  }
  th {
    color: var(--cd-grey--700);
    font-weight: 400;
    width: 40%;
  }
  .map {
    flex: 1;
  }
</style>
