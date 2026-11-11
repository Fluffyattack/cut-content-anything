// Model viewer: turn a model around freely, zoom, switch skins and play its animations.
import * as THREE from "./vendor/three/three.module.js";
import { OrbitControls } from "./vendor/three/OrbitControls.js";
import { decodeBase64 } from "./level-explorer.js";

function loadSkin(dataUrl) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => {
      const texture = new THREE.Texture(image);
      texture.flipY = false;
      texture.magFilter = THREE.NearestFilter;
      texture.minFilter = THREE.NearestMipmapLinearFilter;
      texture.colorSpace = THREE.SRGBColorSpace;
      texture.needsUpdate = true;
      resolve(texture);
    };
    image.onerror = () => reject(new Error("The skin could not be decoded."));
    image.src = dataUrl;
  });
}

// Start with an idle or movement loop if there is one, otherwise with the longest animation.
function preferredAnimation(animations) {
  for (const prefix of ["stand", "idle", "walk", "run", "fly", "swim"]) {
    const match = animations.find((animation) => animation.name.toLowerCase().startsWith(prefix) && animation.frame_count > 1);
    if (match) return match;
  }
  return [...animations].sort((a, b) => b.frame_count - a.frame_count)[0];
}

export class ModelViewer {
  constructor(stage, { onStatus } = {}) {
    this.stage = stage;
    this.onStatus = onStatus || (() => {});
    this.playing = true;
    this.speed = 1;
    this.framePosition = 0;
    this.lastFrameTime = performance.now();
    this.disposed = false;
  }

  async show(model) {
    this.model = model;
    const holder = document.createElement("div");
    holder.className = "stage-canvas";
    this.stage.append(holder);
    this.renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    holder.append(this.renderer.domElement);
    this.renderer.domElement.setAttribute("aria-label", "3D view of the model. Drag to turn it, use the mouse wheel to zoom.");
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x111318);
    this.camera = new THREE.PerspectiveCamera(45, 1, 0.5, 5000);
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x404050, 2.2));
    const sun = new THREE.DirectionalLight(0xffffff, 1.4);
    sun.position.set(80, 140, 100);
    this.scene.add(sun);

    this.onStatus("Decoding skins…");
    this.skins = await Promise.all(model.skins.map((skin) => loadSkin(skin.image)));
    this.sourceVertices = new Uint32Array(decodeBase64(model.source_vertices).buffer);
    this.frames = model.frames.map((frame) => decodeBase64(frame.positions));
    const vertexCount = this.sourceVertices.length;
    this.geometry = new THREE.BufferGeometry();
    this.positions = new Float32Array(vertexCount * 3);
    this.geometry.setAttribute("position", new THREE.BufferAttribute(this.positions, 3));
    this.geometry.setAttribute("uv", new THREE.BufferAttribute(new Float32Array(decodeBase64(model.uv).buffer), 2));
    this.geometry.setIndex(new THREE.BufferAttribute(new Uint32Array(decodeBase64(model.indices).buffer), 1));
    this.litMaterial = new THREE.MeshLambertMaterial({ map: this.skins[0], side: THREE.DoubleSide });
    this.flatMaterial = new THREE.MeshBasicMaterial({ map: this.skins[0], side: THREE.DoubleSide });
    this.mesh = new THREE.Mesh(this.geometry, this.litMaterial);
    this.scene.add(this.mesh);

    this.animation = preferredAnimation(model.animations) || { name: "frame", first_frame: 0, frame_count: model.frames.length };
    this.applyFrame(this.animation.first_frame, this.animation.first_frame, 0);
    this.fitCamera();
    const grid = new THREE.GridHelper(this.radius * 4, 16, 0x3a3f49, 0x22262e);
    grid.position.y = this.geometry.boundingBox.min.y;
    this.scene.add(grid);

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.target.copy(this.centre);
    this.controls.minDistance = this.radius * 0.3;
    this.controls.maxDistance = this.radius * 12;
    this.controls.update();
    this.buildToolbar();

    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(this.stage);
    this.resize();
    this.renderer.setAnimationLoop(() => this.frame());
    this.onStatus("");
  }

  // Quake stores each coordinate as one byte: position = scale * byte + translate (Z up).
  applyFrame(frameA, frameB, blend) {
    const { scale, translate } = this.model;
    const first = this.frames[frameA];
    const second = this.frames[frameB];
    const positions = this.positions;
    for (let index = 0; index < this.sourceVertices.length; index += 1) {
      const source = this.sourceVertices[index] * 3;
      const x = scale[0] * (first[source] + (second[source] - first[source]) * blend) + translate[0];
      const y = scale[1] * (first[source + 1] + (second[source + 1] - first[source + 1]) * blend) + translate[1];
      const z = scale[2] * (first[source + 2] + (second[source + 2] - first[source + 2]) * blend) + translate[2];
      positions[index * 3] = x;
      positions[index * 3 + 1] = z;
      positions[index * 3 + 2] = -y;
    }
    this.geometry.attributes.position.needsUpdate = true;
    this.geometry.computeVertexNormals();
    this.geometry.computeBoundingBox();
  }

  fitCamera() {
    this.geometry.computeBoundingSphere();
    const sphere = this.geometry.boundingSphere;
    this.centre = sphere.center.clone();
    this.radius = Math.max(sphere.radius, 4);
    this.camera.position.set(this.centre.x + this.radius * 1.6, this.centre.y + this.radius * 0.8, this.centre.z + this.radius * 2.2);
    this.camera.near = this.radius / 50;
    this.camera.far = this.radius * 60;
    this.camera.updateProjectionMatrix();
    this.camera.lookAt(this.centre);
    this.startPosition = this.camera.position.clone();
  }

  buildToolbar() {
    const model = this.model;
    const toolbar = document.createElement("div");
    toolbar.className = "toolbar";
    const animationOptions = model.animations
      .map((animation, index) => `<option value="${index}"${animation === this.animation ? " selected" : ""}>${animation.name} (${animation.frame_count} frame${animation.frame_count === 1 ? "" : "s"})</option>`)
      .join("");
    const skinOptions = model.skins.map((skin, index) => `<option value="${index}">${skin.name}</option>`).join("");
    toolbar.innerHTML = `
      <span class="mode-badge">Drag to turn · wheel to zoom · right-drag to move</span>
      <label>Animation <select data-option="animation">${animationOptions}</select></label>
      <button type="button" data-option="play">Pause</button>
      <label>Frame <input type="range" data-option="frame" min="0" max="${Math.max(0, this.animation.frame_count - 1)}" step="1" value="0"></label>
      <label>Speed <select data-option="speed"><option>0.25</option><option>0.5</option><option selected>1</option><option>2</option></select></label>
      <label>Skin <select data-option="skin">${skinOptions}</select></label>
      <label><input type="checkbox" data-option="lit" checked> Shading</label>
      <label><input type="checkbox" data-option="wire"> Wireframe</label>
      <label><input type="checkbox" data-option="spin"> Spin</label>
      <button type="button" data-option="reset" class="secondary">Reset view</button>
      <span class="hint" data-option="frame-name"></span>`;
    const pick = (name) => toolbar.querySelector(`[data-option="${name}"]`);
    pick("animation").addEventListener("change", (event) => {
      this.animation = model.animations[Number(event.target.value)];
      this.framePosition = 0;
      pick("frame").max = Math.max(0, this.animation.frame_count - 1);
    });
    pick("play").addEventListener("click", (event) => {
      this.playing = !this.playing;
      event.target.textContent = this.playing ? "Pause" : "Play";
    });
    pick("frame").addEventListener("input", (event) => {
      this.playing = false;
      pick("play").textContent = "Play";
      this.framePosition = Number(event.target.value);
    });
    pick("speed").addEventListener("change", (event) => { this.speed = Number(event.target.value); });
    pick("skin").addEventListener("change", (event) => {
      const skin = this.skins[Number(event.target.value)];
      this.litMaterial.map = skin;
      this.flatMaterial.map = skin;
      this.litMaterial.needsUpdate = this.flatMaterial.needsUpdate = true;
    });
    pick("lit").addEventListener("change", (event) => { this.mesh.material = event.target.checked ? this.litMaterial : this.flatMaterial; });
    pick("wire").addEventListener("change", (event) => { this.litMaterial.wireframe = this.flatMaterial.wireframe = event.target.checked; });
    pick("spin").addEventListener("change", (event) => { this.controls.autoRotate = event.target.checked; });
    pick("reset").addEventListener("click", () => {
      this.camera.position.copy(this.startPosition);
      this.controls.target.copy(this.centre);
      this.controls.update();
    });
    this.frameSlider = pick("frame");
    this.frameLabel = pick("frame-name");
    this.stage.append(toolbar);
  }

  resize() {
    const width = this.stage.clientWidth || 1;
    const height = this.stage.clientHeight || 1;
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
  }

  frame() {
    if (this.disposed) return;
    const now = performance.now();
    const delta = Math.min((now - this.lastFrameTime) / 1000, 0.1);
    this.lastFrameTime = now;
    const count = this.animation.frame_count;
    if (this.playing && count > 1) {
      this.framePosition = (this.framePosition + delta * this.model.frames_per_second * this.speed) % count;
    }
    const whole = Math.floor(this.framePosition);
    const next = count > 1 ? (whole + 1) % count : whole;
    const first = this.animation.first_frame;
    this.applyFrame(first + whole, first + next, this.playing ? this.framePosition - whole : 0);
    if (this.playing) this.frameSlider.value = String(whole);
    this.frameLabel.textContent = `frame ${first + whole}: ${this.model.frames[first + whole].name}`;
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
    this.stage.dataset.cameraAzimuth = this.controls.getAzimuthalAngle().toFixed(3);
    this.stage.dataset.currentFrame = String(first + whole);
  }

  dispose() {
    this.disposed = true;
    if (this.renderer) this.renderer.setAnimationLoop(null);
    if (this.controls) this.controls.dispose();
    if (this.resizeObserver) this.resizeObserver.disconnect();
    (this.skins || []).forEach((skin) => skin.dispose());
    if (this.geometry) this.geometry.dispose();
    if (this.litMaterial) { this.litMaterial.dispose(); this.flatMaterial.dispose(); }
    if (this.renderer) { this.renderer.dispose(); this.renderer.forceContextLoss(); }
  }
}
