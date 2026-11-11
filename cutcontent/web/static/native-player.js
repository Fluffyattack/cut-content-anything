// Screens and sound come from the running local interpreter, never a preview.
function node(tag, attributes = {}, children = []) {
  const result = document.createElement(tag);
  for (const [name, value] of Object.entries(attributes)) {
    if (name === "text") result.textContent = value;
    else if (name.startsWith("on")) result.addEventListener(name.slice(2), value);
    else result.setAttribute(name, value);
  }
  result.append(...children);
  return result;
}

export class NativePlayer {
  constructor(stage, { api, token, buildId, recipe }) {
    this.stage = stage;
    this.api = api;
    this.token = token;
    this.buildId = buildId;
    this.recipe = recipe;
    this.disposed = false;
    this.busy = false;
    this.session = null;
    this.soundUrl = null;
    this.points = [];
    this.root = node("div", { class: "native-player" });
    this.status = node("p", { class: "native-status", role: "status", text: "Starting game…" });
    this.screen = node("img", { class: "native-screen", alt: "Actual top and bottom game screens", draggable: "false", tabindex: "0" });
    this.screen.addEventListener("load", () => { if (!this.disposed) this.stage.dataset.ready = "native-game"; });
    this.frames = node("select", { "aria-label": "Input duration" }, [
      ...[6, 30, 60, 180].map((frames) => node("option", { value: frames, text: `${frames} frames` })),
    ]);
    this.drawButton = node("select", { "aria-label": "Hold a button while drawing" }, [
      node("option", { value: "", text: "Touch" }), node("option", { value: "up", text: "Directional pad + touch" }),
      node("option", { value: "a", text: "A + Touch" }), node("option", { value: "l", text: "L + Touch" }),
      node("option", { value: "r", text: "R + Touch" }),
    ]);
    const button = (label, action) => node("button", { type: "button", text: label, onclick: action });
    this.microphoneButton = button("Emulated blowing", () => this.operate({ action: "microphone", frames: 120 }));
    this.microphoneButton.hidden = true;
    this.controls = node("div", { class: "native-controls" }, [
      ...[["↑", "up"], ["←", "left"], ["↓", "down"], ["→", "right"], ["A", "a"], ["B", "b"],
        ["X", "x"], ["Y", "y"], ["L", "l"], ["R", "r"], ["Start", "start"], ["Select", "select"]]
        .map(([label, key]) => button(label, () => this.operate({ action: "button", button: key, frames: Number(this.frames.value) }))),
      this.frames, button("Advance", () => this.operate({ action: "step", frames: Number(this.frames.value) })),
      this.drawButton, this.microphoneButton,
    ]);
    this.sound = node("audio", { controls: "", "aria-label": "Recorded game audio" });
    const soundButton = button("Load game audio", () => this.loadSound());
    this.root.append(this.status, this.controls,
      node("p", { class: "hint", text: "Use the buttons or arrow keys. Click or draw on the bottom screen. Each input advances the game." }),
      this.screen, node("div", { class: "native-sound" }, [soundButton, this.sound]));
    this.stage.replaceChildren(this.root);
    this.keyListener = (event) => {
      if (this.disposed || this.busy || event.ctrlKey || event.metaKey || event.altKey) return;
      if (["INPUT", "SELECT", "TEXTAREA"].includes(event.target.tagName)) return;
      const mapping = { ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right",
        z: "a", x: "b", a: "y", s: "x", q: "l", w: "r", Enter: "start", Shift: "select" };
      if (mapping[event.key]) {
        event.preventDefault();
        this.operate({ action: "button", button: mapping[event.key], frames: Number(this.frames.value) });
      }
    };
    document.addEventListener("keydown", this.keyListener);
    const pointAt = (event) => {
      const bounds = this.screen.getBoundingClientRect();
      const x = Math.floor((event.clientX - bounds.left) / bounds.width * 256);
      const y = Math.floor((event.clientY - bounds.top) / bounds.height * 384) - 192;
      return x >= 0 && x <= 255 && y >= 0 && y <= 191 ? [x, y] : null;
    };
    this.screen.addEventListener("pointerdown", (event) => {
      const point = pointAt(event);
      if (!point || this.busy || !this.session) return;
      event.preventDefault();
      this.screen.setPointerCapture(event.pointerId);
      this.points = [point];
    });
    this.screen.addEventListener("pointermove", (event) => {
      if (!this.points.length || this.points.length >= 128) return;
      const point = pointAt(event);
      const last = this.points[this.points.length - 1];
      if (point && (Math.abs(point[0] - last[0]) + Math.abs(point[1] - last[1]) >= 3)) this.points.push(point);
    });
    this.screen.addEventListener("pointerup", () => {
      if (!this.points.length) return;
      const points = this.points;
      this.points = [];
      this.operate({ action: "touch", points, button: this.drawButton.value, frames: Number(this.frames.value) });
    });
    this.screen.addEventListener("pointercancel", () => { this.points = []; });
    this.started = this.start();
  }

  resource(name, extra = "") {
    return `/api/native-session/${this.session}/${name}?token=${encodeURIComponent(this.token)}${extra}`;
  }

  setBusy(busy) {
    this.busy = busy;
    for (const control of this.root.querySelectorAll("button, select")) control.disabled = busy || !this.session;
  }

  showState(payload) {
    if (this.disposed) return;
    this.state = payload.state;
    this.microphoneButton.hidden = !payload.state.microphone_supported;
    this.root.dataset.frames = String(payload.state.frames_executed);
    const sound = payload.state.audio_nonzero_samples > 0 ? "Game audio recorded" : "No audio signal recorded yet";
    const save = payload.state.save?.restored_from_disk ? "Private save loaded" : payload.state.save_persistence_supported ? "Private saves enabled" : "Save persistence not confirmed";
    this.status.textContent = `${payload.state.frames_executed} frames executed · ${sound} · ${save}`;
    this.screen.src = this.resource("frame.png", `&capture=${payload.capture}`);
  }

  async start() {
    this.setBusy(true);
    try {
      const result = await this.api(`native-launch/${this.buildId}`, { method: "POST", body: JSON.stringify({ recipe: this.recipe || "" }) });
      this.session = result.session_id;
      if (this.disposed) {
        await this.api(`native-session/${this.session}/stop`, { method: "POST", body: "{}" });
        return;
      }
      this.showState(result);
    } catch (error) {
      if (!this.disposed) { this.status.textContent = `Game launch failed: ${error.message}`; this.stage.dataset.ready = "error"; }
    } finally { this.setBusy(false); }
  }

  async operate(operation) {
    if (this.busy || this.disposed || !this.session) return;
    this.setBusy(true);
    try {
      const result = await this.api(`native-session/${this.session}/input`, { method: "POST", body: JSON.stringify(operation) });
      this.showState(result);
    } catch (error) {
      if (!this.disposed) this.status.textContent = `Input failed: ${error.message}`;
    } finally { this.setBusy(false); }
  }

  async loadSound() {
    if (this.busy || this.disposed || !this.session) return;
    this.setBusy(true);
    try {
      const response = await fetch(this.resource("audio.wav"));
      if (!response.ok) throw new Error((await response.json()).error || "Could not load game audio.");
      const blob = await response.blob();
      if (this.disposed) return;
      if (this.soundUrl) URL.revokeObjectURL(this.soundUrl);
      this.soundUrl = URL.createObjectURL(blob);
      this.sound.src = this.soundUrl;
      this.sound.load();
    } catch (error) { if (!this.disposed) this.status.textContent = error.message; }
    finally { this.setBusy(false); }
  }

  dispose() {
    this.disposed = true;
    document.removeEventListener("keydown", this.keyListener);
    this.sound.pause();
    if (this.soundUrl) URL.revokeObjectURL(this.soundUrl);
    if (this.session) this.api(`native-session/${this.session}/stop`, { method: "POST", body: "{}", keepalive: true }).catch(() => {});
    this.root.remove();
  }
}
