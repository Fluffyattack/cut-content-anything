// Cut Content Anything – web interface logic.
import { LevelExplorer } from "./level-explorer.js";
import { ModelViewer } from "./model-viewer.js";
import { NativePlayer } from "./native-player.js";

const token = document.querySelector('meta[name="cutcontent-token"]').content;
const $ = (selector) => document.querySelector(selector);

const KIND_LABELS = {
  map: "Levels", model: "Models", texture: "Textures", image: "Images", sprite: "Sprites", sound: "Sounds",
  music: "Music", video: "Videos", text: "Text & dialogue", entity: "Entities", code: "Code", file: "Files",
  rom_region: "ROM regions", header: "Headers",
};
const KIND_GLYPHS = {
  map: "MAP", model: "MODEL", sound: "SOUND", music: "MUSIC", text: "TEXT", code: "CODE", entity: "ENTITY",
  file: "FILE", video: "VIDEO", rom_region: "ROM", header: "HEADER", image: "IMAGE", texture: "TEXTURE", sprite: "SPRITE",
};
// Gallery order: things you can look at or listen to first, plain code and files last.
const KIND_ORDER = ["map", "model", "entity", "texture", "sprite", "image", "sound", "music", "video", "text", "rom_region", "header", "code", "file"];
const kindRank = (kind) => (KIND_ORDER.indexOf(kind) + 1) || KIND_ORDER.length + 1;
const LEVEL_TITLES = {
  present_in_data: "Present in the data",
  possibly_unused: "Possibly unused",
  loaded_under_test: "Loaded under test conditions",
  reachable_in_normal_play: "Reachable in normal play",
};
const STATUS_TEXT = {
  yes: "yes", no: "no", likely: "likely", unlikely: "unlikely", unknown: "unknown", not_checked: "not checked", not_analysed: "not analysed",
};
const METHOD_TEXT = { static: "static analysis", runtime: "observed at runtime", agent: "recorded by an agent or person", none: "no check" };

const state = { games: [], report: null, kind: "all", status: "findings", search: "", question: "", viewer: null, currentItem: null, selectedPath: null };

async function api(path, options = {}) {
  const response = await fetch(`/api/${path}`, {
    ...options,
    headers: { "X-CutContent-Token": token, "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const isJson = (response.headers.get("Content-Type") || "").includes("application/json");
  const payload = isJson ? await response.json() : await response.text();
  if (!response.ok) throw new Error((payload && payload.error) || `Request failed (${response.status})`);
  return payload;
}
const previewUrl = (buildId, itemId, extra = "") => `/api/preview/${buildId}/${itemId}?token=${encodeURIComponent(token)}${extra}`;

function element(tag, attributes = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) if (child !== null && child !== undefined) node.append(child);
  return node;
}

function toast(message) {
  const box = $("#toast");
  box.textContent = message;
  box.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { box.hidden = true; }, 3500);
}

function showDialog(title, content) {
  $("#dialog-title").textContent = title;
  const holder = $("#dialog-content");
  holder.replaceChildren(content);
  $("#dialog").hidden = false;
}
$("#dialog-close").addEventListener("click", () => { $("#dialog").hidden = true; });

// ------------------------------------------------------------------ library
async function loadOverview() {
  try {
    const overview = await api("overview");
    renderFolders(overview.folders);
    state.games = overview.games;
    renderGames();
  } catch (error) {
    $("#game-list").replaceChildren(element("p", { class: "hint", text: `Could not load the library: ${error.message}` }));
  } finally {
    // Finish initial loading before a refresh can replace the same library view.
    $("#refresh-library").disabled = false;
  }
  refreshDoctorPill();
}

function renderFolders(folders) {
  $("#folder-list").replaceChildren(
    ...folders.map((folder) => element("li", { class: folder.exists ? "" : "missing" },
      folder.path, element("span", { class: "source", text: folder.source + (folder.exists ? "" : " – not found") }))),
  );
}

function renderGames() {
  const list = $("#game-list");
  if (!state.games.length) {
    list.replaceChildren(element("p", { class: "hint", text: "No games found in the allowed folders. Create demo data with 'cutcontent demo create' or allow a folder, then refresh." }));
    return;
  }
  list.replaceChildren(...state.games.map((game) => element("div", { class: "game" },
    element("h3", { text: game.title }),
    element("div", { class: "platform", text: game.platform }),
    ...game.builds.map((build) => {
      const report = build.report;
      const stateText = report ? `${report.statistics.findings} findings in ${report.statistics.items} items · scanned ${report.scanned_at.slice(0, 16).replace("T", " ")}` : "not scanned yet";
      return element("div", { class: `build${state.selectedPath === build.path ? " selected" : ""}`, "data-path": build.path },
        element("div", { class: "label", text: `${build.format_name} – ${build.build_label}` }),
        element("div", { class: "state", text: stateText }),
        element("div", { class: "buttons" },
          report ? element("button", { type: "button", class: "primary", text: "Open", onclick: () => openBuild(build.build_id, build.path) }) : null,
          element("button", { type: "button", class: report ? "secondary" : "primary", text: report ? "Scan again" : "Scan", onclick: (event) => scanBuild(build.path, event.target) })));
    }))));
}

async function refreshLibrary() {
  const button = $("#refresh-library");
  button.disabled = true;
  button.textContent = "Searching…";
  try {
    const result = await api("library", { method: "POST", body: "{}" });
    state.games = result.games;
    renderGames();
    toast(`${state.games.length} game(s) found in the allowed folders.`);
  } catch (error) {
    toast(`Refresh failed: ${error.message}`);
  } finally {
    button.disabled = false;
    button.textContent = "Refresh library";
  }
}
$("#refresh-library").addEventListener("click", refreshLibrary);

async function scanBuild(path, button) {
  if (button) { button.disabled = true; button.textContent = "Scanning…"; }
  try {
    const { job_id: jobId } = await api("scan", { method: "POST", body: JSON.stringify({ path }) });
    let job;
    do {
      await new Promise((resolve) => setTimeout(resolve, 600));
      job = await api(`jobs/${jobId}`);
    } while (job.status === "waiting" || job.status === "running");
    if (job.status === "failed") throw new Error(job.error);
    const overview = await api("overview");
    state.games = overview.games;
    renderGames();
    await openBuild(job.build_id, path);
    toast(`Scan finished: ${job.statistics.findings} findings in ${job.statistics.items} items.`);
  } catch (error) {
    toast(`Scan failed: ${error.message}`);
    if (button) { button.disabled = false; button.textContent = "Scan"; }
  }
}

// --------------------------------------------------------------- build view
async function openBuild(buildId, path) {
  if (state.report?.build_id !== buildId) {
    state.question = "";
    $("#investigation-question").value = "";
  }
  state.report = await api(`report/${buildId}`);
  state.selectedPath = path || state.report.path;
  state.kind = "all";
  state.status = state.report.statistics.findings ? "findings" : "all";
  $("#status-filter").value = state.status;
  renderGames();
  renderBuildView();
}

function renderBuildView() {
  const report = state.report;
  $("#welcome").hidden = true;
  $("#build-view").hidden = false;
  $("#build-platform").textContent = `${report.platform} · ${report.format_name}`;
  $("#build-title").textContent = `${report.title} – ${report.build_label}`;
  $("#build-path").textContent = report.path;
  const stats = report.statistics;
  $("#build-stats").textContent = `${stats.items} items · ${stats.findings} possible cut-content findings · scanned ${report.scanned_at.replace("T", " ").slice(0, 16)} UTC`;
  $("#build-limit-list").replaceChildren(...[...report.limits, ...report.warnings].map((text) => element("li", { text })));
  renderNativeLaunch(report);
  renderDirectoryMatches(report.build_id);
  const kinds = Object.keys(stats.items_by_kind).sort((a, b) => (KIND_LABELS[a] || a).localeCompare(KIND_LABELS[b] || b));
  const chip = (kind, label, count) => element("button", {
    type: "button", class: `chip${state.kind === kind ? " active" : ""}`, text: `${label} (${count})`,
    onclick: () => { state.kind = kind; renderBuildView(); },
  });
  $("#kind-filters").replaceChildren(chip("all", "Everything", stats.items), ...kinds.map((kind) => chip(kind, KIND_LABELS[kind] || kind, stats.items_by_kind[kind])));
  renderGallery();
}

function renderNativeLaunch(report) {
  const panel = $("#native-launch");
  const gameplay = report.native_gameplay;
  panel.hidden = !gameplay;
  panel.replaceChildren();
  if (!gameplay) return;
  const launchButton = (label, recipe = "") => {
    const button = element("button", { type: "button", text: label, onclick: () => openNativeGame(recipe) });
    button.disabled = !gameplay.available;
    button.title = gameplay.reason;
    return button;
  };
  panel.append(element("h3", { text: "Test in the actual game" }), element("p", { class: "hint", text: gameplay.reason }),
    launchButton("Start game"));
  for (const recipe of gameplay.recipes || []) {
    panel.append(element("div", { class: "developer-recipe" }, launchButton(recipe.title, recipe.id),
      element("p", { text: recipe.observed }), element("p", { class: "hint", text: recipe.description }),
      element("p", { class: "hint", text: recipe.limits })));
  }
}

// Documented content from the shared directory (DIRECTORY.md) for this build.
const DIRECTORY_STATEMENTS = [["present_in_data", "Present in the data"], ["possibly_unused", "Possibly unused"],
  ["loaded_under_test", "Loaded under test conditions"], ["reachable_in_normal_play", "Reachable in normal play"]];
const DIRECTORY_HEADING = "Documented content (shared directory)";

async function renderDirectoryMatches(buildId) {
  const panel = $("#directory-matches");
  if (panel.dataset.buildId === buildId) return;
  panel.dataset.buildId = buildId;
  panel.hidden = false;
  panel.replaceChildren(element("h3", { text: DIRECTORY_HEADING }), element("p", { class: "hint", text: "Checking…" }));
  let result;
  try {
    result = await api(`directory/${buildId}`);
  } catch (error) {
    if (panel.dataset.buildId === buildId) panel.replaceChildren(element("h3", { text: DIRECTORY_HEADING }), element("p", { class: "hint", text: error.message }));
    return;
  }
  if (panel.dataset.buildId !== buildId) return;
  const heading = element("h3", { text: `${DIRECTORY_HEADING}: ${result.matches.length}` });
  if (!result.matches.length) {
    panel.replaceChildren(heading, element("p", { class: "hint", text:
      "Nobody has documented content for this game in the shared directory yet. That says nothing about the game itself. What your agent verifies can be contributed back." }));
    return;
  }
  const list = element("ul", { class: "directory-list" });
  for (const entry of result.matches) {
    const statements = DIRECTORY_STATEMENTS.map(([key, label]) => element("li", { text: `${label}: ${entry.evidence[key].answer}` }));
    const sources = entry.sources.map((url) => element("a", { href: url, target: "_blank", rel: "noopener noreferrer", text: new URL(url).hostname }));
    list.append(element("li", { class: "directory-entry" },
      element("p", {}, element("code", { text: entry.item }), ` · ${entry.kind} · `, element("strong", { text: entry.quality })),
      element("p", { text: entry.summary }),
      element("ul", { class: "directory-evidence" }, statements),
      element("p", { class: "hint", text: `Matched by ${entry.match_reason}. Checked ${entry.checked}.` }),
      element("p", { class: "hint" }, "Sources: ", ...sources.flatMap((link, index) => (index ? [" · ", link] : [link])))));
  }
  panel.replaceChildren(heading, element("p", { class: "hint", text:
    "Each entry is a hypothesis for this exact build. Verify it here before relying on it." }), list);
}

function openNativeGame(recipe) {
  if (state.viewer && state.viewer.dispose) state.viewer.dispose();
  state.currentItem = null;
  $("#viewer").hidden = false;
  $("#viewer-kind").textContent = "Actual emulator run";
  $("#viewer-title").textContent = state.report.title;
  $("#viewer-explore").hidden = true;
  $("#viewer-game").hidden = true;
  $("#viewer-details").replaceChildren(element("p", { text: "This run uses the local game file. Captures and saves remain private. Starting through a developer menu does not establish normal-play access." }));
  const stage = $("#viewer-stage");
  delete stage.dataset.ready;
  state.viewer = new NativePlayer(stage, { api, token, buildId: state.report.build_id, recipe });
}

$("#status-filter").addEventListener("change", (event) => { state.status = event.target.value; renderGallery(); });
$("#investigation-question").addEventListener("input", (event) => { state.question = event.target.value.trim(); });
$("#search").addEventListener("input", (event) => { state.search = event.target.value.trim().toLowerCase(); renderGallery(); });
$("#rescan").addEventListener("click", (event) => scanBuild(state.report.path, event.target));
$("#copy-task-claude").addEventListener("click", () => copyTask("claude"));
$("#copy-task-codex").addEventListener("click", () => copyTask("codex"));

function visibleItems() {
  const report = state.report;
  return report.items.filter((item) => {
    if (state.kind !== "all" && item.kind !== state.kind) return false;
    if (state.status === "findings" && !item.is_finding) return false;
    if (state.status === "missing" && item.evidence.present_in_data.status !== "no") return false;
    if (state.status === "unreleased" && !["unreleased_candidate", "unreleased_confirmed"].includes(item.release_history?.status)) return false;
    if (state.search && !item.name.toLowerCase().includes(state.search)) return false;
    return true;
  }).sort((a, b) => (Number(b.is_finding) - Number(a.is_finding))
    || (Number(a.evidence.present_in_data.status === "no") - Number(b.evidence.present_in_data.status === "no"))
    || (kindRank(a.kind) - kindRank(b.kind)) || a.name.localeCompare(b.name));
}

function evidenceDots(item) {
  return element("div", { class: "evidence-dots", title: Object.entries(LEVEL_TITLES).map(([level, title]) => `${title}: ${STATUS_TEXT[item.evidence[level].status]}`).join("\n") },
    ...Object.keys(LEVEL_TITLES).map((level) => {
      const status = item.evidence[level].status;
      return element("span", { class: `dot ${level === "possibly_unused" && status === "yes" ? "unused-yes" : status}` });
    }));
}

function findingObservations(item) {
  const observations = [];
  if (item.release_history?.status === "released" && item.release_history.scope === "asset_distribution") observations.push("Included in the release");
  const runtime = item.evidence.loaded_under_test;
  if (runtime.status === "yes" && runtime.method === "runtime" && runtime.access_route === "direct_start") observations.push("Direct launch tested");
  if (item.details?.normal_access_search?.status === "not_found") observations.push("No regular access found");
  return observations;
}

function renderGallery() {
  const items = visibleItems();
  const limit = 1500;
  $("#result-count").textContent = items.length > limit ? `${items.length} items (showing the first ${limit})` : `${items.length} items`;
  const fragment = document.createDocumentFragment();
  for (const item of items.slice(0, limit)) {
    const thumb = element("div", { class: "thumb" });
    if (item.thumbnail && item.preview.supported) {
      thumb.append(element("img", { src: previewUrl(state.report.build_id, item.id, "&thumbnail=1"), alt: "", loading: "lazy" }));
    } else {
      thumb.append(element("span", { class: "glyph", text: KIND_GLYPHS[item.kind] || item.kind.toUpperCase() }));
    }
    if (item.is_finding) thumb.append(element("span", { class: "finding-flag", text: "possible cut content" }));
    if (["unreleased_candidate", "unreleased_confirmed"].includes(item.release_history?.status)) {
      const scope = { playable_release: "Playable content", asset_distribution: "Data", project_release: "Game" }[item.release_history.scope] || "Content";
      const status = item.release_history.status === "unreleased_confirmed" ? "supported" : "candidate";
      thumb.append(element("span", { class: "release-flag", text: `${scope}: unreleased · ${status}` }));
    }
    fragment.append(element("button", {
      type: "button", class: `card${item.is_finding ? " finding" : ""}`, "data-item-id": item.id, "data-kind": item.kind,
      onclick: () => openViewer(item),
    }, thumb, element("div", { class: "body" },
      element("span", { class: "kind", text: item.kind.replace("_", " ") }),
      element("span", { class: "name", text: item.name }),
      findingObservations(item).length ? element("span", { class: "finding-summary", text: findingObservations(item).join(" · ") }) : null,
      evidenceDots(item))));
  }
  $("#gallery").replaceChildren(fragment);
}

// ------------------------------------------------------------------ viewer
function closeViewer() {
  if (state.viewer && state.viewer.dispose) state.viewer.dispose();
  state.viewer = null;
  state.currentItem = null;
  $("#viewer-stage").replaceChildren();
  $("#viewer").hidden = true;
}
$("#viewer-close").addEventListener("click", closeViewer);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !$("#viewer").hidden && !document.pointerLockElement) closeViewer();
});

function stageMessage(title, text) {
  return element("div", { class: "stage-message" }, element("div", {}, element("strong", { text: title }), text || ""));
}

async function openViewer(item) {
  if (state.viewer && state.viewer.dispose) state.viewer.dispose();
  state.viewer = null;
  state.currentItem = item;
  const report = state.report;
  $("#viewer").hidden = false;
  $("#viewer-kind").textContent = `${item.kind.replace("_", " ")}${item.is_finding ? " · Search category: Possible cut content" : ""}`;
  $("#viewer-title").textContent = item.name;
  const stage = $("#viewer-stage");
  stage.replaceChildren();
  delete stage.dataset.ready;
  renderDetails(item);

  const isLevel = item.preview.viewer === "map3d";
  const explore = $("#viewer-explore");
  const game = $("#viewer-game");
  explore.hidden = !(isLevel && item.kind !== "model");
  game.hidden = !(isLevel && item.kind !== "model");
  game.disabled = !(report.game_launch && report.game_launch.available);
  game.title = (report.game_launch && report.game_launch.reason) || "No game start is available for this platform.";

  if (!item.preview.supported) {
    stage.append(stageMessage("No preview for this item", item.preview.reason));
    stage.dataset.ready = "info";
    return;
  }
  try {
    if (isLevel) await showLevel(item);
    else if (item.preview.viewer === "model3d") await showModel(item);
    else if (item.preview.viewer === "image") showImage(item);
    else if (item.preview.viewer === "audio") showAudio(item);
    else if (item.preview.viewer === "text") await showText(item);
    else if (item.preview.viewer === "tiles") showTiles(item);
    else stage.append(stageMessage("Details only", item.preview.reason || "This item has no visual preview."));
  } catch (error) {
    stage.replaceChildren(stageMessage("The preview failed", error.message));
    stage.dataset.ready = "error";
  }
}

async function fetchJsonPreview(item) {
  const response = await fetch(previewUrl(state.report.build_id, item.id));
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || "Preview failed");
  return payload;
}

async function showLevel(item) {
  const stage = $("#viewer-stage");
  const status = stageMessage("Loading the level…", "Converting geometry, textures and light maps.");
  stage.append(status);
  const level = await fetchJsonPreview(item);
  if (state.currentItem !== item) return;
  status.remove();
  const explorer = new LevelExplorer(stage);
  state.viewer = explorer;
  const options = { mode: item.kind === "model" || item.decoded_scene ? "orbit" : "fly" };
  if (item.kind === "entity") options.focusEntity = item.reference.index;
  await explorer.show(level, options);
  stage.dataset.ready = "level";
}
$("#viewer-explore").addEventListener("click", () => { if (state.currentItem) openViewer(state.currentItem); });

$("#viewer-game").addEventListener("click", async () => {
  const item = state.currentItem;
  if (!item) return;
  const button = $("#viewer-game");
  button.disabled = true;
  try {
    const launch = await api(`game-launch/${state.report.build_id}/${item.id}`, { method: "POST", body: "{}" });
    if (state.currentItem !== item) return;
    if (state.viewer && state.viewer.dispose) state.viewer.dispose();
    const stage = $("#viewer-stage");
    const frame = element("iframe", { src: launch.url, title: `Play ${launch.map} in Qwasm`, class: "game-frame", allow: "autoplay; fullscreen", sandbox: "allow-scripts allow-same-origin allow-pointer-lock" });
    stage.replaceChildren(frame);
    delete stage.dataset.ready;
    const receive = (event) => {
      if (event.origin !== location.origin || event.source !== frame.contentWindow) return;
      if (event.data?.type === "cutcontent-game-ready") stage.dataset.ready = "game";
      if (event.data?.type === "cutcontent-game-error") { stage.dataset.ready = "error"; toast(event.data.message); }
    };
    window.addEventListener("message", receive);
    state.viewer = { dispose: () => { window.removeEventListener("message", receive); frame.remove(); } };
  } catch (error) {
    toast(`Game start failed: ${error.message}`);
  } finally {
    if (state.currentItem === item) button.disabled = !state.report.game_launch?.available;
  }
});

async function showModel(item) {
  const stage = $("#viewer-stage");
  const status = stageMessage("Loading the model…", "");
  stage.append(status);
  const model = await fetchJsonPreview(item);
  if (state.currentItem !== item) return;
  status.remove();
  const viewer = new ModelViewer(stage);
  state.viewer = viewer;
  await viewer.show(model);
  stage.dataset.ready = "model";
}

function showImage(item) {
  const stage = $("#viewer-stage");
  let zoom = 4;
  const image = element("img", { src: previewUrl(state.report.build_id, item.id), alt: item.name });
  const holder = element("div", { class: "image-stage" }, image);
  const zoomLabel = element("span", { class: "hint" });
  const applyZoom = () => {
    if (!image.naturalWidth) return;
    image.style.width = `${image.naturalWidth * zoom}px`;
    image.style.height = `${image.naturalHeight * zoom}px`;
    zoomLabel.textContent = `${image.naturalWidth} × ${image.naturalHeight} pixels · zoom ×${zoom}`;
  };
  image.addEventListener("load", () => {
    zoom = Math.max(1, Math.min(8, Math.floor(Math.min(holder.clientWidth / image.naturalWidth, holder.clientHeight / image.naturalHeight)) || 1));
    applyZoom();
    stage.dataset.ready = "image";
  });
  image.addEventListener("error", async () => {
    const response = await fetch(image.src);
    const payload = await response.json().catch(() => ({}));
    stage.replaceChildren(stageMessage("The image could not be shown", payload.error || ""));
  });
  const toolbar = element("div", { class: "toolbar" },
    element("span", { class: "mode-badge", text: "Mouse wheel or buttons to zoom · scroll to move" }),
    ...[1, 2, 4, 8, 16].map((factor) => element("button", { type: "button", class: "secondary", text: `×${factor}`, onclick: () => { zoom = factor; applyZoom(); } })),
    zoomLabel);
  holder.addEventListener("wheel", (event) => {
    event.preventDefault();
    zoom = Math.max(1, Math.min(32, event.deltaY < 0 ? zoom * 2 : zoom / 2));
    applyZoom();
  }, { passive: false });
  stage.append(toolbar, holder);
}

function showAudio(item) {
  const stage = $("#viewer-stage");
  const url = previewUrl(state.report.build_id, item.id);
  const audio = element("audio", { src: url, controls: true, preload: "auto" });
  const canvas = element("canvas", { width: 900, height: 180, "aria-label": "Waveform" });
  const info = element("p", { class: "hint", text: "Decoding the waveform…" });
  stage.append(element("div", { class: "audio-stage" }, canvas, audio, info));
  fetch(url).then((response) => response.arrayBuffer()).then((buffer) => {
    const context = new (window.AudioContext || window.webkitAudioContext)();
    return context.decodeAudioData(buffer).then((decoded) => { context.close(); return decoded; });
  }).then((decoded) => {
    const samples = decoded.getChannelData(0);
    const drawing = canvas.getContext("2d");
    drawing.fillStyle = "#0b0c0f";
    drawing.fillRect(0, 0, canvas.width, canvas.height);
    drawing.strokeStyle = "#f0a63a";
    const step = Math.max(1, Math.floor(samples.length / canvas.width));
    for (let x = 0; x < canvas.width; x += 1) {
      let low = 1, high = -1;
      for (let index = x * step; index < Math.min(samples.length, (x + 1) * step); index += 1) {
        low = Math.min(low, samples[index]);
        high = Math.max(high, samples[index]);
      }
      drawing.beginPath();
      drawing.moveTo(x + 0.5, (1 - high) * canvas.height / 2);
      drawing.lineTo(x + 0.5, (1 - low) * canvas.height / 2);
      drawing.stroke();
    }
    info.textContent = `${decoded.duration.toFixed(2)} s · ${decoded.sampleRate} Hz · ${decoded.numberOfChannels} channel(s)`;
    stage.dataset.ready = "audio";
  }).catch(() => {
    info.textContent = "The waveform could not be decoded by this browser; the player may still work.";
    stage.dataset.ready = "audio";
  });
}

// Tile browser for cartridge ROMs: any part of the ROM drawn as 8 x 8 tiles.
function showTiles(item) {
  const stage = $("#viewer-stage");
  const size = item.location.size || 0;
  let bits = item.reference.bits_per_pixel || 2;
  let offset = 0;
  let columns = 16;
  let zoom = 3;
  const windowBytes = () => 1024 * (bits === 2 ? 16 : 32);
  const image = element("img", { alt: "ROM tiles" });
  const holder = element("div", { class: "image-stage" }, image);
  const offsetInput = element("input", { type: "text", value: "0x0", size: 10, "aria-label": "Offset" });
  const label = element("span", { class: "hint" });
  const load = () => {
    offset = Math.max(0, Math.min(offset, Math.max(0, size - 16)));
    offsetInput.value = `0x${offset.toString(16).toUpperCase()}`;
    image.src = previewUrl(state.report.build_id, item.id, `&offset=${offset}&bits=${bits}&columns=${columns}`);
    label.textContent = `bytes 0x${offset.toString(16).toUpperCase()}–0x${Math.min(size, offset + windowBytes()).toString(16).toUpperCase()} of 0x${size.toString(16).toUpperCase()} · ${bits} bits per pixel`;
  };
  image.addEventListener("load", () => {
    image.style.width = `${image.naturalWidth * zoom}px`;
    image.style.height = `${image.naturalHeight * zoom}px`;
    stage.dataset.ready = "tiles";
  });
  offsetInput.addEventListener("change", () => { offset = Number.parseInt(offsetInput.value, offsetInput.value.startsWith("0x") ? 16 : 10) || 0; load(); });
  const bitsSelect = element("select", { "aria-label": "Bits per pixel" },
    element("option", { value: "2", text: "2 bits per pixel (planar)" }), element("option", { value: "4", text: "4 bits per pixel (packed)" }));
  bitsSelect.value = String(bits);
  bitsSelect.addEventListener("change", () => { bits = Number(bitsSelect.value); load(); });
  const columnSelect = element("select", { "aria-label": "Tiles per row" }, ...[16, 32].map((value) => element("option", { value: String(value), text: `${value} per row` })));
  columnSelect.addEventListener("change", () => { columns = Number(columnSelect.value); load(); });
  const toolbar = element("div", { class: "toolbar" },
    element("button", { type: "button", class: "secondary", text: "◀ previous", onclick: () => { offset -= windowBytes(); load(); } }),
    element("button", { type: "button", class: "secondary", text: "next ▶", onclick: () => { offset += windowBytes(); load(); } }),
    element("label", {}, "Offset ", offsetInput), bitsSelect, columnSelect,
    element("button", { type: "button", class: "secondary", text: "zoom +", onclick: () => { zoom = Math.min(8, zoom + 1); image.dispatchEvent(new Event("load")); } }),
    element("button", { type: "button", class: "secondary", text: "zoom −", onclick: () => { zoom = Math.max(1, zoom - 1); image.dispatchEvent(new Event("load")); } }),
    label);
  stage.append(toolbar, holder);
  load();
}

async function showText(item) {
  const stage = $("#viewer-stage");
  const response = await fetch(previewUrl(state.report.build_id, item.id));
  const text = await response.text();
  if (!response.ok) throw new Error(JSON.parse(text).error);
  const lines = text.split("\n");
  const pre = element("pre", { text });
  const filter = element("input", { type: "search", placeholder: `Filter ${lines.length} lines…`, "aria-label": "Filter lines" });
  filter.addEventListener("input", () => {
    const query = filter.value.toLowerCase();
    pre.textContent = query ? lines.filter((line) => line.toLowerCase().includes(query)).join("\n") : text;
  });
  stage.append(element("div", { class: "text-stage" }, filter, pre));
  stage.dataset.ready = "text";
}

function renderDetails(item) {
  const report = state.report;
  const panel = $("#viewer-details");
  const parts = [];
  const observations = findingObservations(item);
  if (observations.length) parts.push(element("h3", { text: "Supported findings" }),
    element("p", { class: "observed-facts", "data-observed-facts": "", text: observations.join(" · ") }));
  if (item.finding_reasons.length) {
    parts.push(element("h3", { text: "Search leads" }), element("ul", { class: "reasons" }, ...item.finding_reasons.map((reason) => element("li", { text: reason }))));
  }
  parts.push(element("h3", { text: "Evidence" }));
  parts.push(element("table", { class: "evidence-table" }, ...Object.entries(LEVEL_TITLES).map(([level, title]) => {
    const evidence = item.evidence[level];
    const statusClass = level === "possibly_unused" && evidence.status === "yes" ? "possibly-yes" : evidence.status;
    return element("tr", { "data-level": level },
      element("td", { text: title }),
      element("td", {},
        element("span", { class: `status ${statusClass}`, text: STATUS_TEXT[evidence.status] || evidence.status }),
        element("div", { text: evidence.basis }),
        element("div", { class: "method", text: (METHOD_TEXT[evidence.method] || evidence.method) + (evidence.recorded ? ` · recorded ${evidence.recorded_at || ""}` : "") })));
  })));

  const publication = item.release_history;
  if (publication) {
    parts.push(element("h3", { text: "Release history" }),
      element("p", { class: `notice release-${publication.status}`, text: publication.label }),
      element("p", { text: publication.basis }));
    if (publication.scope_label) parts.push(element("p", { class: "hint", text: publication.scope_label }));
    if (publication.checked_at) parts.push(element("p", { class: "hint", text: `Assessment recorded: ${publication.checked_at}` }));
    if (publication.sources?.length) parts.push(element("ul", {}, ...publication.sources.map((source) =>
      element("li", {}, element("a", { href: source, target: "_blank", rel: "noopener noreferrer", text: source })))));
  }
  if (item.decoded_scene) parts.push(element("h3", { text: "Decoded map" }),
    element("p", { text: item.decoded_scene.basis }),
    element("p", { class: "hint", text: `${item.decoded_scene.triangles} triangles · Decoder: ${item.decoded_scene.decoder}` }));
  parts.push(element("h3", { text: "Location" }));
  const location = element("dl", { class: "location" });
  for (const [key, value] of Object.entries(item.location)) {
    if (value === "" || value === null || value === undefined) continue;
    location.append(element("dt", { text: key.replaceAll("_", " ") }), element("dd", { text: String(value) }));
  }
  parts.push(location);

  const details = Object.entries(item.details || {}).filter(([key]) => key !== "entity");
  if (details.length) {
    parts.push(element("h3", { text: "Details" }));
    const list = element("dl", { class: "location" });
    for (const [key, value] of details) {
      list.append(element("dt", { text: key.replaceAll("_", " ") }), element("dd", { text: Array.isArray(value) ? value.join(", ") : typeof value === "object" ? JSON.stringify(value) : String(value) }));
    }
    parts.push(list);
  }
  if (item.details && item.details.entity) {
    parts.push(element("h3", { text: "Entity keys" }));
    const list = element("dl", { class: "location" });
    for (const [key, value] of Object.entries(item.details.entity)) list.append(element("dt", { text: key }), element("dd", { text: value }));
    parts.push(list);
  }
  if (item.preview.viewer === "map3d" && item.kind !== "model") {
    parts.push(element("h3", { text: "Game start" }), element("p", { class: "notice", text: (report.game_launch && report.game_launch.reason) || "Not available." }));
  }
  if (!item.preview.supported && item.preview.reason) {
    parts.push(element("h3", { text: "Preview" }), element("p", { class: "notice info", text: item.preview.reason }));
  }
  parts.push(element("h3", { text: "Limits of these checks" }), element("ul", { class: "reasons" },
    ...[...item.limits, "See also the scan-wide limits above the gallery."].map((text) => element("li", { text }))));
  panel.replaceChildren(...parts);
}

// --------------------------------------------------------- tasks for agents
async function copyText(text, label) {
  try {
    await navigator.clipboard.writeText(text);
    toast(`${label} copied to the clipboard.`);
  } catch (error) {
    const area = element("textarea", { readonly: true });
    area.value = text;
    showDialog(label, element("div", {}, element("p", { class: "hint", text: "The clipboard is not available here; copy the text below." }), area));
    area.select();
  }
}

async function copyTask(client, itemIds = []) {
  if (!state.report) return;
  const query = new URLSearchParams({ client, items: itemIds.join(","), question: state.question });
  const { text } = await api(`task/${state.report.build_id}?${query}`);
  state.lastTask = text;
  document.body.dataset.lastTaskClient = client;
  await copyText(text, client === "claude" ? "Task for Claude Code" : "Task for Codex");
}
$("#viewer-task-claude").addEventListener("click", () => copyTask("claude", state.currentItem ? [state.currentItem.id] : []));
$("#viewer-task-codex").addEventListener("click", () => copyTask("codex", state.currentItem ? [state.currentItem.id] : []));

// -------------------------------------------------------- doctor & formats
async function refreshDoctorPill() {
  try {
    const { checks } = await api("doctor");
    const problems = checks.filter((check) => check.status === "problem").length;
    const warnings = checks.filter((check) => check.status === "warning").length;
    const pill = $("#show-doctor");
    pill.className = `status-pill ${problems ? "problem" : warnings ? "warning" : "ok"}`;
    pill.textContent = problems ? `Setup: ${problems} problem(s)` : warnings ? `Setup: ${warnings} warning(s)` : "Setup: OK";
  } catch (error) { /* the button still opens the dialog */ }
}
$("#show-doctor").addEventListener("click", async () => {
  const { checks } = await api("doctor");
  showDialog("Setup check (cutcontent doctor)", element("table", {},
    element("tr", {}, element("th", { text: "Check" }), element("th", { text: "Status" }), element("th", { text: "Detail" })),
    ...checks.map((check) => element("tr", {}, element("td", { text: check.check }), element("td", { class: `check ${check.status}`, text: check.status }), element("td", { text: check.detail })))));
});
$("#show-formats").addEventListener("click", async () => {
  const { formats } = await api("formats");
  showDialog("Supported formats (what is really tested)", element("table", {},
    element("tr", {}, ...["Platform", "Format", "Level", "Analysis", "Preview", "Not supported", "Tested with"].map((text) => element("th", { text }))),
    ...formats.map((row) => element("tr", {}, ...[`${row.platform}`, `${row.format_name} (${row.extensions})`, row.level, row.analysis, row.previews, row.not_supported, row.tested_with].map((text) => element("td", { text }))))));
});

loadOverview();
