// The engine and all writable files live in this frame's browser memory.
"use strict";
var Module;
const canvas = document.getElementById("canvas");
const statusLine = document.getElementById("status");
const output = document.getElementById("output");
let stopped = false;

function notify(type, detail) {
  if (parent !== window) parent.postMessage({ type, ...detail }, location.origin);
}

function fail(message) {
  stopped = true;
  document.body.dataset.failed = "true";
  statusLine.hidden = false;
  statusLine.textContent = `The engine could not start: ${message}`;
  document.getElementById("engine-log").open = true;
  notify("cutcontent-game-error", { message: String(message) });
}

function log(text) {
  output.textContent = (output.textContent + String(text) + "\n").slice(-30000);
  output.scrollTop = output.scrollHeight;
  if (/^(Error:|Host_Error:)/.test(String(text))) fail(String(text));
}

canvas.addEventListener("contextmenu", (event) => event.preventDefault());
canvas.addEventListener("click", () => {
  canvas.focus();
  const request = canvas.requestPointerLock();
  if (request && request.catch) request.catch(() => {});
});

async function start() {
  const response = await fetch("manifest.json");
  if (!response.ok) throw new Error(`Game session unavailable (${response.status}).`);
  const manifest = await response.json();
  document.getElementById("level-name").textContent = `Qwasm · ${manifest.map}`;
  Module = {
    canvas,
    arguments: ["-basedir", "/game", "-mem", "64", "-width", "640", "-height", "480", "+exec", "cutcontent-controls.cfg", "+map", manifest.map],
    print: log,
    printErr: log,
    locateFile: (name) => name,
    onAbort: fail,
    onExit: (code) => { if (code) fail(`Engine exited with code ${code}.`); },
    setStatus: (text) => { if (text && !stopped) statusLine.textContent = text; },
    hideConsole: () => {},
    showConsole: () => { document.getElementById("engine-log").open = true; },
    setGamma: (gamma) => { canvas.style.filter = `brightness(${(1.35 - Number(gamma)) * 2})`; },
    // Pointer lock needs a click. Do not steal it during loading or on every key.
    captureMouse: () => {},
    preRun: [() => {
      Module.addRunDependency("selected-game");
      (async () => {
        const filesystem = Module.FS;
        filesystem.mkdirTree("/game/id1");
        let loaded = 0;
        for (const file of manifest.files) {
          statusLine.textContent = `Loading game files: ${++loaded} / ${manifest.files.length}`;
          const dataResponse = await fetch(file.url);
          if (!dataResponse.ok) throw new Error(`Could not read ${file.name} (${dataResponse.status}).`);
          const data = new Uint8Array(await dataResponse.arrayBuffer());
          if (data.length !== file.size) throw new Error(`The size of ${file.name} has changed. Scan again.`);
          const path = `/game/id1/${file.name}`;
          filesystem.mkdirTree(path.substring(0, path.lastIndexOf("/")));
          filesystem.writeFile(path, data);
        }
        filesystem.writeFile("/game/id1/cutcontent-controls.cfg", 'bind w "+forward"\nbind s "+back"\nbind a "+moveleft"\nbind d "+moveright"\nbind SPACE "+jump"\nbind CTRL "+attack"\n');
        statusLine.textContent = "Starting the selected level…";
        Module.removeRunDependency("selected-game");
      })().catch(fail);
    }],
    onRuntimeInitialized: () => {
      const observe = () => {
        if (stopped) return;
        try {
          const state = JSON.parse(Module.ccall("cutcontent_runtime_state", "string", [], []));
          window.cutcontentRuntimeState = state;
          if (state.loaded) {
            document.body.dataset.ready = "game";
            statusLine.hidden = true;
            notify("cutcontent-game-ready", { state });
          }
        } catch (error) { fail(error.message); }
      };
      setInterval(observe, 250);
    },
  };
  const engine = document.createElement("script");
  engine.src = "engine.js";
  engine.onerror = () => fail("The engine script could not be loaded.");
  document.head.append(engine);
}

window.addEventListener("error", (event) => fail(event.message));
start().catch((error) => fail(error.message));
