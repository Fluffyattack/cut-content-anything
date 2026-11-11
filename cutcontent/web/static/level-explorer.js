// "Explore in 3D": a free camera through a level's real geometry, textures and light maps.
// This is a viewer, not a game start: there is no collision, no game logic and no enemies.
import * as THREE from "./vendor/three/three.module.js";
import { OrbitControls } from "./vendor/three/OrbitControls.js";

const NORMAL_SPEED = 320;          // Quake units per second (the player's running speed)
const FAST_FACTOR = 3;
const MOUSE_SENSITIVITY = 0.0022;
// Walk mode uses the level's own collision hull for a standing player (Quake units).
const GRAVITY = 800;
const JUMP_SPEED = 270;
const STEP_HEIGHT = 18;
const CONTENTS_SOLID = -2;
const CONTENTS_SKY = -6;
const ENTITY_COLOURS = [
  ["monster_", 0xef6b6b], ["item_", 0x4cc38a], ["weapon_", 0x4cc38a], ["light", 0xe5c454],
  ["info_player", 0x6aa8ff], ["info_", 0x6aa8ff], ["trigger_", 0xb38cff], ["func_", 0xb38cff],
];

export function decodeBase64(text) {
  const binary = atob(text);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return bytes;
}
const decodeFloats = (text) => new Float32Array(decodeBase64(text).buffer);

function loadTexture(dataUrl, { pixelated = true, repeat = true } = {}) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => {
      const texture = new THREE.Texture(image);
      texture.flipY = false;
      texture.wrapS = texture.wrapT = repeat ? THREE.RepeatWrapping : THREE.ClampToEdgeWrapping;
      texture.magFilter = pixelated ? THREE.NearestFilter : THREE.LinearFilter;
      texture.minFilter = pixelated ? THREE.NearestMipmapLinearFilter : THREE.LinearFilter;
      texture.generateMipmaps = pixelated;
      texture.needsUpdate = true;
      resolve(texture);
    };
    image.onerror = () => reject(new Error("A texture could not be decoded."));
    image.src = dataUrl;
  });
}

const SURFACE_VERTEX_SHADER = `
  attribute vec2 lightUv;
  varying vec2 vUv;
  varying vec2 vLightUv;
  void main() {
    vUv = uv;
    vLightUv = lightUv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }`;
const SURFACE_FRAGMENT_SHADER = `
  uniform sampler2D surfaceTexture;
  uniform sampler2D lightTexture;
  uniform float useLight;
  uniform float warp;
  uniform float time;
  uniform float opacity;
  uniform float alphaCut;
  varying vec2 vUv;
  varying vec2 vLightUv;
  void main() {
    vec2 uv = vUv;
    if (warp > 0.5) uv += 0.05 * sin(vUv.yx * 6.2831 + time);
    vec4 colour = texture2D(surfaceTexture, uv);
    if (colour.a < alphaCut) discard;
    vec3 light = useLight > 0.5 ? texture2D(lightTexture, vLightUv).rgb * 2.0 : vec3(1.0);
    gl_FragColor = vec4(colour.rgb * light, opacity);
  }`;

export class LevelExplorer {
  constructor(stage, { onStatus } = {}) {
    this.stage = stage;
    this.onStatus = onStatus || (() => {});
    this.keys = new Set();
    this.yaw = 0;
    this.pitch = 0;
    this.speedFactor = 1;
    this.materials = [];
    this.entityMarkers = [];
    this.disposed = false;
    this.walking = false;
    this.verticalSpeed = 0;
    this.onGround = false;
    this.startTime = performance.now();
    this.lastFrameTime = this.startTime;
    this.distanceTravelled = 0;
  }

  async show(level, options = {}) {
    this.navigationSpeed = Number(level.navigation?.speed) || NORMAL_SPEED;
    const holder = document.createElement("div");
    holder.className = "stage-canvas";
    this.stage.append(holder);
    this.renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    holder.append(this.renderer.domElement);
    this.renderer.domElement.tabIndex = 0;
    this.renderer.domElement.setAttribute("aria-label", "3D view of the level. Click to look around, move with W A S D.");
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x0b0c10);
    this.camera = new THREE.PerspectiveCamera(75, 1, 1, 30000);
    this.camera.rotation.order = "YXZ";

    this.onStatus("Decoding textures…");
    const lightTexture = await loadTexture(level.lightmap.image, { pixelated: false, repeat: false });
    const textures = await Promise.all(level.textures.map((texture) => loadTexture(texture.image)));
    const world = new THREE.Group();
    level.groups.forEach((group) => {
      const info = level.textures[group.texture];
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position", new THREE.BufferAttribute(decodeFloats(group.positions), 3));
      geometry.setAttribute("uv", new THREE.BufferAttribute(decodeFloats(group.uv), 2));
      geometry.setAttribute("lightUv", new THREE.BufferAttribute(decodeFloats(group.light_uv), 2));
      const material = new THREE.ShaderMaterial({
        uniforms: {
          surfaceTexture: { value: textures[group.texture] },
          lightTexture: { value: lightTexture },
          useLight: { value: 1 },
          warp: { value: info.kind === "liquid" ? 1 : 0 },
          time: { value: 0 },
          opacity: { value: info.kind === "liquid" ? 0.75 : 1 },
          alphaCut: { value: info.kind === "transparent" ? 0.5 : 0 },
        },
        vertexShader: SURFACE_VERTEX_SHADER,
        fragmentShader: SURFACE_FRAGMENT_SHADER,
        side: THREE.DoubleSide,
        transparent: info.kind === "liquid",
        depthWrite: info.kind !== "liquid",
      });
      this.materials.push(material);
      const mesh = new THREE.Mesh(geometry, material);
      mesh.name = info.name;
      world.add(mesh);
    });
    this.scene.add(world);
    this.world = world;
    this.addEntityMarkers(level.entities, options.focusEntity);

    this.levelBounds = new THREE.Box3().setFromObject(world);
    if (level.navigation?.far) {
      this.camera.far = Number(level.navigation.far);
      this.camera.updateProjectionMatrix();
    }
    if (level.collision) {
      this.collision = {
        planes: new Float32Array(decodeBase64(level.collision.planes).buffer),
        nodes: new Int32Array(decodeBase64(level.collision.clip_nodes).buffer),
        head: level.collision.head_node,
        eyeHeight: level.collision.eye_height,
      };
    }
    this.mode = options.mode === "orbit" ? "orbit" : "fly";
    if (this.mode === "orbit") this.setUpOrbit();
    else this.setUpFly(level.spawn, options.focusEntity, level.entities);

    this.buildToolbar(level);
    this.hud = document.createElement("div");
    this.hud.className = "hud";
    this.stage.append(this.hud);
    this.label = document.createElement("div");
    this.label.className = "entity-label";
    this.label.hidden = true;
    this.stage.append(this.label);

    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(this.stage);
    this.resize();
    this.renderer.setAnimationLoop(() => this.frame());
    this.onStatus("");
    this.renderer.domElement.focus();
  }

  addEntityMarkers(entities, focusIndex) {
    this.entityGroup = new THREE.Group();
    const geometry = new THREE.BoxGeometry(12, 12, 12);
    for (const entity of entities) {
      if (entity.classname === "worldspawn") continue;
      const focused = entity.index === focusIndex;
      const colour = focused ? 0xff4fd8 : (ENTITY_COLOURS.find(([prefix]) => entity.classname.startsWith(prefix)) || [null, 0x9aa1ad])[1];
      const material = new THREE.MeshBasicMaterial({ color: colour, wireframe: !focused, transparent: true, opacity: focused ? 0.9 : 0.75 });
      const marker = new THREE.Mesh(geometry, material);
      marker.position.set(...entity.origin);
      if (focused) marker.scale.setScalar(2.2);
      marker.userData.entity = entity;
      this.entityGroup.add(marker);
      this.entityMarkers.push(marker);
    }
    this.scene.add(this.entityGroup);
  }

  setUpFly(spawn, focusIndex, entities) {
    const focus = entities.find((entity) => entity.index === focusIndex);
    if (focus) {
      const [x, y, z] = focus.origin;
      this.camera.position.set(x - 120, y + 60, z + 120);
      this.camera.lookAt(x, y, z);
      this.yaw = this.camera.rotation.y;
      this.pitch = this.camera.rotation.x;
    } else if (spawn) {
      this.camera.position.set(...spawn.origin);
      this.yaw = THREE.MathUtils.degToRad(spawn.angle) - Math.PI / 2;
    } else {
      const centre = this.levelBounds.getCenter(new THREE.Vector3());
      this.camera.position.copy(centre);
    }
    this.startPosition = this.camera.position.clone();
    const canvas = this.renderer.domElement;
    this.handlers = {
      keydown: (event) => {
        if (event.target.closest && event.target.closest("input, select, textarea")) return;
        this.keys.add(event.code);
        if (["Space", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(event.code)) event.preventDefault();
      },
      keyup: (event) => this.keys.delete(event.code),
      blur: () => this.keys.clear(),
      mousedown: (event) => {
        this.dragging = { x: event.clientX, y: event.clientY };
        canvas.focus();
        if (canvas.requestPointerLock && event.button === 0) {
          try { const request = canvas.requestPointerLock(); if (request && request.catch) request.catch(() => {}); } catch (error) { /* drag still works */ }
        }
      },
      mouseup: () => { this.dragging = null; },
      mousemove: (event) => {
        const locked = document.pointerLockElement === canvas;
        if (locked) {
          // Browsers sometimes report one huge jump right after the pointer is captured; skip it.
          if (this.skipNextMovement || Math.abs(event.movementX) > 250 || Math.abs(event.movementY) > 250) {
            this.skipNextMovement = false;
            return;
          }
          this.turn(event.movementX, event.movementY);
        } else if (this.dragging) {
          this.turn(event.clientX - this.dragging.x, event.clientY - this.dragging.y);
          this.dragging = { x: event.clientX, y: event.clientY };
        } else {
          this.pointer = { x: event.offsetX, y: event.offsetY };
        }
      },
      pointerlockchange: () => {
        this.skipNextMovement = true;
        this.dragging = null;
      },
      wheel: (event) => {
        event.preventDefault();
        this.speedFactor = THREE.MathUtils.clamp(this.speedFactor * (event.deltaY < 0 ? 1.15 : 1 / 1.15), 0.1, 10);
      },
    };
    window.addEventListener("keydown", this.handlers.keydown);
    window.addEventListener("keyup", this.handlers.keyup);
    window.addEventListener("blur", this.handlers.blur);
    canvas.addEventListener("mousedown", this.handlers.mousedown);
    window.addEventListener("mouseup", this.handlers.mouseup);
    canvas.addEventListener("mousemove", this.handlers.mousemove);
    canvas.addEventListener("wheel", this.handlers.wheel, { passive: false });
    document.addEventListener("pointerlockchange", this.handlers.pointerlockchange);
  }

  setUpOrbit() {
    const centre = this.levelBounds.getCenter(new THREE.Vector3());
    const size = this.levelBounds.getSize(new THREE.Vector3()).length() || 64;
    this.camera.position.set(centre.x + size * 0.9, centre.y + size * 0.6, centre.z + size * 0.9);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.target.copy(centre);
    this.controls.enableDamping = true;
    this.controls.update();
    this.startPosition = this.camera.position.clone();
  }

  // ---------------------------------------------------------------- walk mode
  // Viewer space is (x, z, -y) of Quake space.
  static toQuake(position) { return [position.x, -position.z, position.y]; }

  hullContents(x, y, z) {
    const { planes, nodes } = this.collision;
    let node = this.collision.head;
    for (let steps = 0; node >= 0 && steps < 100000; steps += 1) {
      const plane = nodes[node * 3] * 4;
      const side = x * planes[plane] + y * planes[plane + 1] + z * planes[plane + 2] - planes[plane + 3];
      node = side >= 0 ? nodes[node * 3 + 1] : nodes[node * 3 + 2];
    }
    return node;
  }

  blocked(x, y, z) {
    const contents = this.hullContents(x, y, z);
    return contents === CONTENTS_SOLID || contents === CONTENTS_SKY;
  }

  startWalking() {
    if (!this.collision) return false;
    const [x, y, eyeZ] = LevelExplorer.toQuake(this.camera.position);
    let z = eyeZ - this.collision.eyeHeight;
    for (let lift = 0; lift < 12 && this.blocked(x, y, z); lift += 1) z += 16;
    if (this.blocked(x, y, z)) {
      this.walkMessage = "No free space here - fly into an open room first, then switch walking on.";
      return false;
    }
    this.walkMessage = "";
    this.verticalSpeed = 0;
    this.camera.position.set(x, z + this.collision.eyeHeight, -y);
    return true;
  }

  moveWalking(delta, keys) {
    let [x, y, eyeZ] = LevelExplorer.toQuake(this.camera.position);
    let z = eyeZ - this.collision.eyeHeight;
    const forwardX = Math.cos(this.yaw + Math.PI / 2);
    const forwardY = Math.sin(this.yaw + Math.PI / 2);
    let wishX = 0;
    let wishY = 0;
    if (keys.has("KeyW") || keys.has("ArrowUp")) { wishX += forwardX; wishY += forwardY; }
    if (keys.has("KeyS") || keys.has("ArrowDown")) { wishX -= forwardX; wishY -= forwardY; }
    if (keys.has("KeyD")) { wishX += forwardY; wishY -= forwardX; }
    if (keys.has("KeyA")) { wishX -= forwardY; wishY += forwardX; }
    const length = Math.hypot(wishX, wishY);
    if (length > 0) {
      const fast = keys.has("ShiftLeft") || keys.has("ShiftRight") ? 1.6 : 1;
      const distance = this.navigationSpeed * this.speedFactor * fast * delta;
      // move in small pieces so a slow frame rate cannot carry the player through a thin wall
      const pieces = Math.max(1, Math.ceil(distance / 8));
      const moveX = (wishX / length) * (distance / pieces);
      const moveY = (wishY / length) * (distance / pieces);
      const before = [x, y];
      for (let piece = 0; piece < pieces; piece += 1) {
        if (!this.blocked(x + moveX, y + moveY, z)) { x += moveX; y += moveY; }
        else if (!this.blocked(x, y, z + STEP_HEIGHT) && !this.blocked(x + moveX, y + moveY, z + STEP_HEIGHT)) { x += moveX; y += moveY; z += STEP_HEIGHT; }
        else if (!this.blocked(x + moveX, y, z)) { x += moveX; }
        else if (!this.blocked(x, y + moveY, z)) { y += moveY; }
        else break;
      }
      this.distanceTravelled += Math.hypot(x - before[0], y - before[1]);
    }
    if (this.onGround && keys.has("Space")) { this.verticalSpeed = JUMP_SPEED; this.onGround = false; }
    this.verticalSpeed -= GRAVITY * delta;
    const fall = this.verticalSpeed * delta;
    if (!this.blocked(x, y, z + fall)) {
      z += fall;
      this.onGround = false;
    } else {
      if (this.verticalSpeed < 0) {
        for (let settle = 0; settle < 32 && !this.blocked(x, y, z - 1); settle += 1) z -= 1;
        this.onGround = true;
      }
      this.verticalSpeed = 0;
    }
    this.camera.rotation.set(this.pitch, this.yaw, 0);
    this.camera.position.set(x, z + this.collision.eyeHeight, -y);
  }

  turn(deltaX, deltaY) {
    this.yaw -= deltaX * MOUSE_SENSITIVITY;
    this.pitch = THREE.MathUtils.clamp(this.pitch - deltaY * MOUSE_SENSITIVITY, -Math.PI / 2 + 0.01, Math.PI / 2 - 0.01);
  }

  buildToolbar(level) {
    const toolbar = document.createElement("div");
    toolbar.className = "toolbar";
    const badge = this.mode === "orbit" ? "Rotate view: drag · zoom: wheel · pan: right-drag" : "Free camera (noclip) – not a game start";
    toolbar.innerHTML = `
      <span class="mode-badge">${badge}</span>
      <label title="${this.collision ? "Walk on the floor with the level's collision; Space jumps" : "This level has no collision hull for a player"}"><input type="checkbox" data-option="walk"${this.collision && this.mode !== "orbit" ? "" : " disabled"}> Walk (collision)</label>
      <label><input type="checkbox" data-option="light" checked> Light maps</label>
      <label><input type="checkbox" data-option="entities" checked> Entity markers</label>
      <span class="hint">${level.statistics.triangles.toLocaleString()} triangles · ${level.textures.length} textures · ${level.layout}${level.lightmap.coloured ? " · coloured light" : ""}</span>
      <button type="button" data-option="reset" class="secondary">Back to start</button>`;
    toolbar.querySelector('[data-option="light"]').addEventListener("change", (event) => {
      this.materials.forEach((material) => { material.uniforms.useLight.value = event.target.checked ? 1 : 0; });
    });
    toolbar.querySelector('[data-option="entities"]').addEventListener("change", (event) => { this.entityGroup.visible = event.target.checked; });
    const walkBox = toolbar.querySelector('[data-option="walk"]');
    walkBox.addEventListener("change", (event) => {
      this.walking = event.target.checked && this.startWalking();
      event.target.checked = this.walking;
      toolbar.querySelector(".mode-badge").textContent = this.walking
        ? "Walking with the level's collision – not a game start"
        : "Free camera (noclip) – not a game start";
      this.renderer.domElement.focus();
    });
    this.walkCheckbox = walkBox;
    toolbar.querySelector('[data-option="reset"]').addEventListener("click", () => {
      this.camera.position.copy(this.startPosition);
      if (this.controls) this.controls.update();
      this.renderer.domElement.focus();
    });
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
    const time = (now - this.startTime) / 1000;
    this.materials.forEach((material) => { material.uniforms.time.value = time; });
    if (this.mode === "orbit") {
      this.controls.update();
    } else {
      this.moveFlyCamera(delta);
    }
    this.updateHoverLabel();
    this.renderer.render(this.scene, this.camera);
    this.updateHud();
  }

  moveFlyCamera(delta) {
    const keys = this.keys;
    const turnSpeed = 1.8 * delta;
    if (keys.has("ArrowLeft")) this.yaw += turnSpeed;
    if (keys.has("ArrowRight")) this.yaw -= turnSpeed;
    if (this.walking) {
      this.moveWalking(delta, keys);
      return;
    }
    this.camera.rotation.set(this.pitch, this.yaw, 0);
    const forward = new THREE.Vector3(0, 0, -1).applyEuler(this.camera.rotation);
    const right = new THREE.Vector3(1, 0, 0).applyEuler(this.camera.rotation);
    const move = new THREE.Vector3();
    if (keys.has("KeyW") || keys.has("ArrowUp")) move.add(forward);
    if (keys.has("KeyS") || keys.has("ArrowDown")) move.sub(forward);
    if (keys.has("KeyD")) move.add(right);
    if (keys.has("KeyA")) move.sub(right);
    if (keys.has("Space") || keys.has("KeyE")) move.y += 1;
    if (keys.has("KeyC") || keys.has("KeyQ") || keys.has("ControlLeft")) move.y -= 1;
    if (move.lengthSq() > 0) {
      const fast = keys.has("ShiftLeft") || keys.has("ShiftRight") ? FAST_FACTOR : 1;
      move.normalize().multiplyScalar(this.navigationSpeed * this.speedFactor * fast * delta);
      this.camera.position.add(move);
      this.distanceTravelled += move.length();
    }
  }

  updateHoverLabel() {
    if (!this.pointer || !this.entityGroup.visible) { this.label.hidden = true; return; }
    const canvas = this.renderer.domElement;
    const raycaster = new THREE.Raycaster();
    raycaster.setFromCamera(new THREE.Vector2((this.pointer.x / canvas.clientWidth) * 2 - 1, -(this.pointer.y / canvas.clientHeight) * 2 + 1), this.camera);
    const hit = raycaster.intersectObjects(this.entityMarkers, false)[0];
    if (!hit) { this.label.hidden = true; return; }
    const entity = hit.object.userData.entity;
    this.label.textContent = `${entity.classname}${entity.targetname ? " · " + entity.targetname : ""}`;
    this.label.style.left = `${this.pointer.x}px`;
    this.label.style.top = `${this.pointer.y + 52}px`;
    this.label.hidden = false;
  }

  updateHud() {
    if (!this.hud) return;
    const position = this.camera.position;
    // show Quake coordinates (x, y, z) again: viewer space is (x, z, -y)
    const quake = `${Math.round(position.x)} ${Math.round(-position.z)} ${Math.round(position.y)}`;
    if (this.mode === "orbit") {
      this.hud.innerHTML = `<strong>3D view</strong> · drag to rotate, wheel to zoom, right-drag to pan`;
    } else {
      const mode = this.walking ? `walking${this.onGround ? "" : " (in the air)"}` : "flying (noclip)";
      const keysHelp = this.walking
        ? "W A S D / arrow keys walk · Space jumps · Shift runs · walls and floors block you (no game logic, no enemies)"
        : "W A S D / arrow keys move · Space/E up · C/Q down · Shift faster · mouse wheel changes speed · hover a marker for its class";
      this.hud.innerHTML = `<strong>Position</strong> ${quake} · ${mode} · speed ×${this.speedFactor.toFixed(1)}<br>
        <span class="keys">Click the view and move the mouse to look (Esc releases it, dragging works too) · ${keysHelp}</span>
        ${this.walkMessage ? `<br><strong>${this.walkMessage}</strong>` : ""}`;
    }
    this.stage.dataset.cameraPosition = quake;
    this.stage.dataset.distanceTravelled = Math.round(this.distanceTravelled);
    this.stage.dataset.walking = String(this.walking);
  }

  dispose() {
    this.disposed = true;
    if (this.renderer) this.renderer.setAnimationLoop(null);
    if (this.handlers) {
      window.removeEventListener("keydown", this.handlers.keydown);
      window.removeEventListener("keyup", this.handlers.keyup);
      window.removeEventListener("blur", this.handlers.blur);
      window.removeEventListener("mouseup", this.handlers.mouseup);
      document.removeEventListener("pointerlockchange", this.handlers.pointerlockchange);
    }
    if (document.pointerLockElement && document.exitPointerLock) document.exitPointerLock();
    if (this.controls) this.controls.dispose();
    if (this.resizeObserver) this.resizeObserver.disconnect();
    if (this.scene) {
      this.scene.traverse((object) => {
        if (object.geometry) object.geometry.dispose();
        if (object.material) {
          const uniforms = object.material.uniforms || {};
          Object.values(uniforms).forEach((uniform) => uniform.value && uniform.value.dispose && uniform.value.dispose());
          object.material.dispose();
        }
      });
    }
    if (this.renderer) {
      this.renderer.dispose();
      this.renderer.forceContextLoss();
    }
  }
}
