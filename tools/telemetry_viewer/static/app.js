const state = {
  events: [],
  bots: new Map(),
  selected: null,
  cursor: 0,
  generation: 0,
  maxEvents: 40000,
  inactiveBotSeconds: 15,
  palette: ["#5ab0ff", "#5fd38d", "#f2bf62", "#ff6b6b", "#b68cff", "#5ad6ff"],
  lastNewEventsAt: 0,
};

const arena = document.getElementById("arena");
const arenaCtx = arena.getContext("2d");
const energyChart = document.getElementById("energyChart");
const energyCtx = energyChart.getContext("2d");
const distanceChart = document.getElementById("distanceChart");
const distanceCtx = distanceChart.getContext("2d");
const gunTimeline = document.getElementById("gunTimeline");
const gunTimelineCtx = gunTimeline.getContext("2d");
const movementTimeline = document.getElementById("movementTimeline");
const movementTimelineCtx = movementTimeline.getContext("2d");

// Events written through DebugLogger.sample (plus turn timing): periodic snapshots, not decisions.
const SAMPLED_EVENTS = new Set([
  "track",
  "search",
  "target.reacquire",
  "wall.avoid",
  "search.wall_avoid",
  "separate",
  "movement.duel_potential",
  "movement.goto_surf",
  "movement.option_surf",
  "movement.minimum_risk",
  "bot.turn_timing",
]);

const modePalette = [
  "#5ab0ff",
  "#5fd38d",
  "#f2bf62",
  "#ff6b6b",
  "#b68cff",
  "#5ad6ff",
  "#e58bd8",
  "#9fb26a",
];

const {
  displayEnergy,
  eventMatchesStreamFilter,
  format,
  gunModeFromEvent,
  movementModeFromEvent,
  normalizeEvent,
  summarizeEvent,
} = window.TelemetryView;

document.getElementById("eventFilter").addEventListener("change", renderEvents);
document.getElementById("onlySelected").addEventListener("change", renderEvents);
document.getElementById("showSamples").addEventListener("change", renderEvents);
document.getElementById("showInactiveBots").addEventListener("change", () => {
  rebuildBots();
  render();
});
document.getElementById("resetTelemetry").addEventListener("click", resetTelemetry);

poll();
setInterval(poll, 1000);
window.addEventListener("resize", () => render());

async function resetTelemetry() {
  if (!window.confirm("Reset telemetry stats for this viewer? Current JSONL event files will be truncated.")) {
    return;
  }
  try {
    const response = await fetch("/api/reset", { method: "POST", cache: "no-store", headers: { "X-Robocode-Telemetry": "1" } });
    const payload = await response.json();
    if (!payload.ok) {
      throw new Error((payload.errors || []).join("; ") || "reset failed");
    }
    state.events = [];
    state.bots.clear();
    state.selected = null;
    state.cursor = payload.cursor || 0;
    state.generation = payload.generation || 0;
    document.getElementById("source").textContent = `reset ${payload.reset?.length || 0} telemetry files`;
    document.getElementById("eventCount").textContent = "0 events";
    render();
    setTimeout(poll, 200);
  } catch (error) {
    document.getElementById("source").textContent = `telemetry reset failed: ${error}`;
  }
}

async function poll() {
  try {
    const response = await fetch(`/api/events?limit=${state.maxEvents}&cursor=${state.cursor}&generation=${state.generation}`, { cache: "no-store" });
    const payload = await response.json();
    const events = payload.events || [];
    const previousGeneration = state.generation;
    const generationChanged = Boolean(previousGeneration && payload.generation && previousGeneration !== payload.generation);
    if (generationChanged) {
      state.selected = null;
    }
    if (state.cursor && !payload.truncated && !generationChanged) {
      state.events.push(...events);
      if (state.events.length > state.maxEvents) {
        state.events = state.events.slice(-state.maxEvents);
      }
    } else {
      state.events = events.slice(-state.maxEvents);
    }
    if (events.length) {
      state.lastNewEventsAt = Date.now();
    }
    state.cursor = payload.cursor || state.cursor;
    state.generation = payload.generation || state.generation;
    const source = document.getElementById("source");
    source.textContent = `${shortPath(payload.dir || "")} · ${(payload.files || []).length} files`;
    source.title = payload.dir || "";
    document.getElementById("eventCount").textContent = `${state.events.length} events`;
    document.getElementById("lastUpdate").textContent = new Date().toLocaleTimeString();
    rebuildBots();
    render();
  } catch (error) {
    document.getElementById("source").textContent = `telemetry unavailable: ${error}`;
  }
}

function rebuildBots() {
  const allBots = new Map();
  const showInactive = document.getElementById("showInactiveBots").checked;
  const newestTimestamp = newestEventTimestamp(state.events);
  for (const event of state.events) {
    if (!event.normalized) event.normalized = normalizeEvent(event);
    const bot = event.bot || "unknown";
    if (!allBots.has(bot)) {
      allBots.set(bot, { name: bot, events: [], latest: null, color: state.palette[allBots.size % state.palette.length] });
    }
    const record = allBots.get(bot);
    record.events.push(event);
    record.latest = event;
  }
  state.bots.clear();
  for (const bot of allBots.values()) {
    if (showInactive || !isInactiveBot(bot, newestTimestamp)) {
      state.bots.set(bot.name, bot);
    }
  }
  if (!state.selected || !state.bots.has(state.selected)) {
    // Default to the bot with the richest telemetry, not whichever logged first.
    let richest = null;
    for (const bot of state.bots.values()) {
      if (!richest || bot.events.length > richest.events.length) richest = bot;
    }
    state.selected = richest?.name || null;
  }
}

function newestEventTimestamp(events) {
  let newest = null;
  for (const event of events) {
    const timestamp = typeof event.ts === "number" && Number.isFinite(event.ts) ? event.ts : null;
    if (timestamp != null && (newest == null || timestamp > newest)) {
      newest = timestamp;
    }
  }
  return newest;
}

function isInactiveBot(bot, newestTimestamp) {
  if (newestTimestamp == null || !bot?.latest) return false;
  const latestEnergy = displayEnergy(numberAt(bot.latest, "state.energy"));
  if (latestEnergy.dead) return true;
  const timestamp = typeof bot.latest.ts === "number" && Number.isFinite(bot.latest.ts) ? bot.latest.ts : null;
  return timestamp != null && newestTimestamp - timestamp > state.inactiveBotSeconds;
}

function render() {
  renderStatus();
  renderTabs();
  renderArena();
  renderMetrics();
  renderSurfDecision();
  renderChart(energyCtx, state.selected, (event) => displayEnergy(numberAt(event, "state.energy")).value, 0, 100, "#5fd38d");
  renderChart(distanceCtx, state.selected, (event) => event.normalized?.distance, 0, null, "#f2bf62");
  renderPerformance();
  renderModeTimeline(gunTimelineCtx, state.selected, gunModeFromEvent);
  renderModeTimeline(movementTimelineCtx, state.selected, movementModeFromEvent);
  renderEvents();
}

function renderTabs() {
  const tabs = document.getElementById("botTabs");
  tabs.replaceChildren();
  for (const bot of state.bots.values()) {
    const button = document.createElement("button");
    const swatch = document.createElement("span");
    swatch.className = "swatch";
    swatch.style.background = bot.color;
    button.append(swatch, document.createTextNode(bot.name));
    button.className = bot.name === state.selected ? "active" : "";
    if (bot.name === state.selected) button.style.color = bot.color;
    button.addEventListener("click", () => {
      state.selected = bot.name;
      render();
    });
    tabs.appendChild(button);
  }
}

function renderStatus() {
  const live = Date.now() - state.lastNewEventsAt < 4000;
  const chip = document.getElementById("liveChip");
  chip.classList.toggle("live", live);
  document.getElementById("liveLabel").textContent = live ? "live" : state.events.length ? "idle" : "waiting";
  const latest = state.bots.get(state.selected)?.latest;
  document.getElementById("turnChip").textContent = `turn ${latest?.turn ?? "-"}`;
}

function shortPath(path) {
  const parts = String(path).split(/[\\/]/).filter(Boolean);
  if (parts.length <= 3) return path;
  return `…/${parts.slice(-3).join("/")}`;
}

function prepareCanvas(ctx) {
  const canvas = ctx.canvas;
  const ratio = window.devicePixelRatio || 1;
  const width = Math.max(10, Math.round(canvas.clientWidth || canvas.width));
  const height = Math.max(10, Math.round(canvas.clientHeight || canvas.height));
  if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) {
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
  }
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);
  return { width, height };
}

function currentRoundEvents(bot) {
  // Events since the bot's turn counter last went backwards, i.e. this round.
  const events = bot?.events || [];
  let start = 0;
  for (let index = 1; index < events.length; index += 1) {
    const previous = events[index - 1].turn;
    const turn = events[index].turn;
    if (typeof previous === "number" && typeof turn === "number" && turn + 5 < previous) start = index;
  }
  return events.slice(start);
}

function hexToRgba(hex, alpha) {
  const value = hex.replace("#", "");
  const r = parseInt(value.slice(0, 2), 16);
  const g = parseInt(value.slice(2, 4), 16);
  const b = parseInt(value.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${alpha})`;
}

function renderArena() {
  const { width: viewWidth, height: viewHeight } = prepareCanvas(arenaCtx);
  const ctx = arenaCtx;
  ctx.fillStyle = "#080b0f";
  ctx.fillRect(0, 0, viewWidth, viewHeight);

  const latest = [...state.bots.values()].map((bot) => bot.latest).filter(Boolean);
  const width = maxValue(latest, "state.arena_width", 800);
  const height = maxValue(latest, "state.arena_height", 600);
  const pad = 22;
  const scale = Math.min((viewWidth - pad * 2) / width, (viewHeight - pad * 2) / height);
  const offsetX = (viewWidth - width * scale) / 2;
  const offsetY = (viewHeight - height * scale) / 2;
  const toX = (x) => offsetX + x * scale;
  const toY = (y) => offsetY + (height - y) * scale;

  const field = ctx.createLinearGradient(0, offsetY, 0, offsetY + height * scale);
  field.addColorStop(0, "#141b23");
  field.addColorStop(1, "#10161c");
  ctx.fillStyle = field;
  ctx.fillRect(offsetX, offsetY, width * scale, height * scale);
  ctx.strokeStyle = "rgba(255,255,255,0.045)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let gx = 100; gx < width; gx += 100) {
    ctx.moveTo(toX(gx), offsetY);
    ctx.lineTo(toX(gx), offsetY + height * scale);
  }
  for (let gy = 100; gy < height; gy += 100) {
    ctx.moveTo(offsetX, toY(gy));
    ctx.lineTo(offsetX + width * scale, toY(gy));
  }
  ctx.stroke();

  ctx.save();
  ctx.beginPath();
  ctx.rect(offsetX, offsetY, width * scale, height * scale);
  ctx.clip();

  const selectedBot = state.bots.get(state.selected);
  const positions = tankViews();

  // Enemy waves the selected bot is surfing, from its own enemy-fire detections.
  if (selectedBot?.latest) {
    const turn = selectedBot.latest.turn;
    const sx = numberAt(selectedBot.latest, "state.x");
    const sy = numberAt(selectedBot.latest, "state.y");
    for (const event of currentRoundEvents(selectedBot)) {
      if (event.event !== "enemy.fire_detected") continue;
      const fields = event.fields || {};
      const ox = fields.fire_source_x;
      const oy = fields.fire_source_y;
      const power = fields.power;
      const fireTurn = fields.inferred_fire_turn;
      if ([ox, oy, power, fireTurn, turn, sx, sy].some((value) => typeof value !== "number")) continue;
      const speed = 20 - 3 * power;
      const radius = speed * (turn - (fireTurn - 1));
      const gap = Math.hypot(sx - ox, sy - oy) - radius;
      if (radius <= 0 || gap < -30) continue;
      const closeness = Math.max(0, Math.min(1, 1 - gap / 260));
      ctx.strokeStyle = "rgba(90,214,255,0.16)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.arc(toX(ox), toY(oy), radius * scale, 0, Math.PI * 2);
      ctx.stroke();
      const bearing = Math.atan2(sy - oy, sx - ox);
      const spread = Math.asin(Math.min(1, 8 / speed));
      ctx.strokeStyle = `rgba(90,214,255,${0.35 + 0.65 * closeness})`;
      ctx.lineWidth = 2 + closeness * 2;
      ctx.shadowColor = "rgba(90,214,255,0.6)";
      ctx.shadowBlur = 8 * closeness;
      ctx.beginPath();
      ctx.arc(toX(ox), toY(oy), radius * scale, -bearing - spread, -bearing + spread);
      ctx.stroke();
      ctx.shadowBlur = 0;
    }
  }

  // Trails.
  for (const bot of state.bots.values()) {
    // One point per turn: a bot can log several events in the same turn.
    const byTurn = new Map();
    for (const event of currentRoundEvents(bot)) {
      const x = numberAt(event, "state.x");
      const y = numberAt(event, "state.y");
      if (x != null && y != null && typeof event.turn === "number") byTurn.set(event.turn, [x, y]);
    }
    const samples = [...byTurn.entries()].sort((a, b) => a[0] - b[0]).slice(-70);
    const points = samples.map(([, point]) => point);
    for (let index = 1; index < points.length; index += 1) {
      // Sparse loggers (position every few dozen turns) would draw misleading straight jumps.
      if (samples[index][0] - samples[index - 1][0] > 6) continue;
      ctx.strokeStyle = hexToRgba(bot.color, 0.5 * index / points.length);
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(toX(points[index - 1][0]), toY(points[index - 1][1]));
      ctx.lineTo(toX(points[index][0]), toY(points[index][1]));
      ctx.stroke();
    }
  }

  // Bullets in flight, from each bot's own fire events.
  for (const bot of state.bots.values()) {
    const turn = bot.latest?.turn;
    if (typeof turn !== "number") continue;
    const roundEvents = currentRoundEvents(bot);
    const finished = new Set(
      roundEvents.filter((event) => event.event === "bullet.hit_bot").map((event) => String(event.fields?.bullet_id)),
    );
    for (const event of roundEvents) {
      if (event.event !== "bullet.fired") continue;
      const fields = event.fields || {};
      if (finished.has(String(fields.bullet_id))) continue;
      const x0 = numberAt(event, "state.x");
      const y0 = numberAt(event, "state.y");
      if (x0 == null || y0 == null || typeof fields.direction !== "number" || typeof fields.power !== "number") continue;
      const age = turn - event.turn;
      if (age < 0 || age > 90) continue;
      const speed = 20 - 3 * fields.power;
      const heading = fields.direction * Math.PI / 180;
      const bx = x0 + Math.cos(heading) * speed * age;
      const by = y0 + Math.sin(heading) * speed * age;
      if (bx < 0 || by < 0 || bx > width || by > height) continue;
      const tx = x0 + Math.cos(heading) * speed * Math.max(0, age - 2);
      const ty = y0 + Math.sin(heading) * speed * Math.max(0, age - 2);
      ctx.strokeStyle = "rgba(242,191,98,0.45)";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(toX(tx), toY(ty));
      ctx.lineTo(toX(bx), toY(by));
      ctx.stroke();
      ctx.fillStyle = "#f2bf62";
      ctx.beginPath();
      ctx.arc(toX(bx), toY(by), 1.5 + fields.power, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  for (const view of positions) {
    drawTank(ctx, view, toX(view.x), toY(view.y), scale, view.name === state.selected, [offsetX, offsetX + width * scale]);
  }
  ctx.restore();

  ctx.strokeStyle = "#2c3744";
  ctx.lineWidth = 1.5;
  ctx.strokeRect(offsetX, offsetY, width * scale, height * scale);

  // Aim point of the selected bot.
  const event = selectedBot?.latest;
  const targetX = numberAt(lastMatchingEvent(selectedBot, (item) => numberAt(item, "fields.predicted_x") != null), "fields.predicted_x");
  const targetY = numberAt(lastMatchingEvent(selectedBot, (item) => numberAt(item, "fields.predicted_y") != null), "fields.predicted_y");
  const px = numberAt(event, "state.x");
  const py = numberAt(event, "state.y");
  if (targetX != null && targetY != null && px != null && py != null) {
    ctx.strokeStyle = "rgba(242,191,98,0.7)";
    ctx.lineWidth = 1;
    ctx.setLineDash([5, 4]);
    ctx.beginPath();
    ctx.moveTo(toX(px), toY(py));
    ctx.lineTo(toX(targetX), toY(targetY));
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.strokeStyle = "#f2bf62";
    ctx.beginPath();
    ctx.arc(toX(targetX), toY(targetY), 6, 0, Math.PI * 2);
    ctx.moveTo(toX(targetX) - 9, toY(targetY));
    ctx.lineTo(toX(targetX) + 9, toY(targetY));
    ctx.moveTo(toX(targetX), toY(targetY) - 9);
    ctx.lineTo(toX(targetX), toY(targetY) + 9);
    ctx.stroke();
  }
}

function tankViews() {
  // Each bot's own latest state, refreshed by fresher scans from other bots' track
  // events: ports log their position only every few dozen turns, and bots without
  // telemetry (Java legacy bots) are only known through the bots that scan them.
  const idToBot = new Map();
  for (const bot of state.bots.values()) {
    const id = numberAt(bot.latest, "state.id");
    if (id != null) idToBot.set(id, bot);
  }
  const scans = new Map();
  for (const scanner of state.bots.values()) {
    for (const event of currentRoundEvents(scanner)) {
      if (event.event !== "track") continue;
      const fields = event.fields || {};
      if (typeof fields.target !== "number" || typeof fields.target_x !== "number" || typeof fields.target_y !== "number") continue;
      const previous = scans.get(fields.target);
      if (!previous || event.turn >= previous.turn) {
        scans.set(fields.target, { turn: event.turn, fields, scanner: scanner.name });
      }
    }
  }

  const views = [];
  for (const bot of state.bots.values()) {
    const event = bot.latest;
    const view = {
      name: bot.name,
      color: bot.color,
      x: numberAt(event, "state.x"),
      y: numberAt(event, "state.y"),
      direction: numberAt(event, "state.direction"),
      gunDirection: numberAt(event, "state.gun_direction"),
      radarDirection: numberAt(event, "state.radar_direction"),
      energy: numberAt(event, "state.energy"),
      scanned: false,
    };
    const id = numberAt(event, "state.id");
    const scan = id != null ? scans.get(id) : null;
    if (scan && typeof event?.turn === "number" && scan.turn > event.turn) {
      Object.assign(view, scanView(scan));
    }
    if (view.x != null && view.y != null) views.push(view);
  }
  for (const [id, scan] of scans) {
    if (idToBot.has(id)) continue;
    views.push({ name: `bot ${id}`, color: "#8b98a5", gunDirection: null, radarDirection: null, ...scanView(scan), scanned: true });
  }
  return views;
}

function scanView(scan) {
  const fields = scan.fields;
  return {
    x: fields.target_x,
    y: fields.target_y,
    direction: typeof fields.target_direction === "number" ? fields.target_direction : null,
    energy: typeof fields.target_energy === "number" ? fields.target_energy : null,
  };
}

function drawTank(ctx, view, cx, cy, scale, selected, bounds = [0, Infinity]) {
  const energy = displayEnergy(view.energy);
  const size = 36 * scale;
  const body = (view.direction ?? 0) * Math.PI / 180;
  const gun = view.gunDirection;
  const radar = view.radarDirection;

  if (radar != null) {
    const angle = -radar * Math.PI / 180;
    const reach = 120 * scale;
    const beam = ctx.createRadialGradient(cx, cy, 0, cx, cy, reach);
    beam.addColorStop(0, "rgba(90,176,255,0.28)");
    beam.addColorStop(1, "rgba(90,176,255,0)");
    ctx.fillStyle = beam;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.arc(cx, cy, reach, angle - 0.18, angle + 0.18);
    ctx.closePath();
    ctx.fill();
  }

  if (selected) {
    ctx.strokeStyle = hexToRgba(view.color, 0.35);
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(cx, cy, size * 0.95, 0, Math.PI * 2);
    ctx.stroke();
  }

  ctx.save();
  ctx.translate(cx, cy);
  ctx.rotate(-body);
  ctx.shadowColor = hexToRgba(view.color, 0.55);
  ctx.shadowBlur = selected ? 14 : 8;
  ctx.fillStyle = hexToRgba(view.color, energy.dead ? 0.25 : view.scanned ? 0.6 : 0.9);
  roundRect(ctx, -size / 2, -size * 0.4, size, size * 0.8, 4);
  ctx.fill();
  ctx.shadowBlur = 0;
  if (view.scanned) {
    ctx.setLineDash([3, 3]);
    ctx.strokeStyle = "rgba(230,237,243,0.7)";
    ctx.lineWidth = 1;
    roundRect(ctx, -size / 2, -size * 0.4, size, size * 0.8, 4);
    ctx.stroke();
    ctx.setLineDash([]);
  }
  ctx.fillStyle = "rgba(0,0,0,0.28)";
  ctx.fillRect(-size / 2, -size * 0.4, size, size * 0.14);
  ctx.fillRect(-size / 2, size * 0.26, size, size * 0.14);
  ctx.restore();

  if (gun != null) {
    const angle = gun * Math.PI / 180;
    ctx.strokeStyle = "#f6f1df";
    ctx.lineWidth = 3;
    ctx.lineCap = "round";
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(cx + Math.cos(angle) * size * 0.85, cy - Math.sin(angle) * size * 0.85);
    ctx.stroke();
    ctx.lineCap = "butt";
  }
  ctx.fillStyle = "#f6f1df";
  ctx.beginPath();
  ctx.arc(cx, cy, Math.max(3, size * 0.16), 0, Math.PI * 2);
  ctx.fill();

  const barWidth = Math.max(44, size * 1.6);
  const barTop = cy - size * 0.95 - 8;
  const value = Math.max(0, Math.min(100, energy.value ?? 0));
  ctx.fillStyle = "rgba(0,0,0,0.5)";
  roundRect(ctx, cx - barWidth / 2 - 1, barTop - 1, barWidth + 2, 7, 3);
  ctx.fill();
  ctx.fillStyle = value > 50 ? "#5fd38d" : value > 20 ? "#f2bf62" : "#ff6b6b";
  roundRect(ctx, cx - barWidth / 2, barTop, barWidth * value / 100, 5, 2.5);
  ctx.fill();

  ctx.font = "600 12px Inter, -apple-system, BlinkMacSystemFont, sans-serif";
  ctx.textAlign = "center";
  ctx.fillStyle = selected ? "#ffffff" : "#c9d4de";
  const label = `${view.name}${view.scanned ? " (scanned)" : ""}  ${energy.label}`;
  const half = ctx.measureText(label).width / 2;
  const labelX = Math.min(Math.max(cx, bounds[0] + half + 6), bounds[1] - half - 6);
  ctx.fillText(label, labelX, barTop - 6);
  ctx.textAlign = "start";
}

function roundRect(ctx, x, y, width, height, radius) {
  ctx.beginPath();
  if (ctx.roundRect) {
    ctx.roundRect(x, y, Math.max(0, width), height, radius);
  } else {
    ctx.rect(x, y, Math.max(0, width), height);
  }
}

function renderMetrics() {
  const selectedPill = document.getElementById("selectedBot");
  selectedPill.textContent = state.selected || "none";
  const bot = state.bots.get(state.selected);
  selectedPill.style.color = bot?.color || "";
  const metrics = document.getElementById("metrics");
  metrics.replaceChildren();
  const latest = bot?.latest;
  const lastFire = lastEvent(bot, "bullet.fired");
  const lastGunSwitch = lastEvent(bot, "gun.switch");
  const lastAim = lastMatchingEvent(bot, (event) => event.normalized?.gunBearing != null || gunModeFromEvent(event));
  // Only track events carry the gun bearing; the latest gun event usually does not.
  const lastBearing = lastMatchingEvent(bot, (event) => event.normalized?.gunBearing != null);
  const lastTrack = lastEvent(bot, "track");
  const lastTarget = lastMatchingEvent(bot, (event) => event.normalized?.target != null);
  const lastDistance = lastMatchingEvent(bot, (event) => event.normalized?.distance != null);
  const lastMovement = lastMatchingEvent(bot, (event) => event.normalized?.movementMode);
  const lastThreat = lastEvent(bot, "enemy.fire_detected");
  const botConfig = lastEvent(bot, "bot.config");
  const energy = displayEnergy(numberAt(latest, "state.energy"));

  const cards = [
    { label: "Energy", value: energy.label, accent: "#5fd38d", energy: energy.value },
    { label: "Turn", value: latest?.turn, accent: "#5ab0ff" },
    { label: "Movement", value: movementModeFromEvent(lastMovement) || "-", accent: "#5ad6ff" },
    { label: "Gun", value: gunModeFromEvent(lastAim) || gunModeFromEvent(lastFire) || lastGunSwitch?.fields?.selected || "-", accent: "#f2bf62" },
    { label: "Firepower", value: format(lastFire?.normalized?.power), accent: "#f2bf62" },
    { label: "Gun Confidence", value: formatPrecise(lastFire?.fields?.gun_confidence, 3), accent: "#f2bf62" },
    { label: "Distance", value: format(lastDistance?.normalized?.distance), accent: "#b68cff" },
    { label: "Target", value: lastTarget?.normalized?.target ?? "-", accent: "#b68cff" },
    { label: "Evasion", value: evasionLabel(lastTrack, lastThreat), accent: "#ff6b6b" },
    { label: "Gun Bearing Error", value: lastBearing ? `${format(lastBearing.normalized.gunBearing)}°` : "-", accent: "#ff6b6b" },
    { label: "Position", value: latest ? `${format(numberAt(latest, "state.x"))}, ${format(numberAt(latest, "state.y"))}` : "-" },
    { label: "Last Event", value: latest?.event || "-" },
    { label: "Live Guns", value: gunList(botConfig?.fields?.selectable_guns), wide: true },
  ];
  if (botConfig?.fields?.forced_gun) {
    cards.push({ label: "Pinned Gun", value: botConfig.fields.forced_gun, wide: true });
  }
  for (const card of cards) {
    const element = document.createElement("div");
    element.className = card.wide ? "metric wide" : "metric";
    if (card.accent) element.style.setProperty("--accent", card.accent);
    let html = `<div class="label">${escapeHtml(card.label)}</div><div class="value">${escapeHtml(card.value ?? "-")}</div>`;
    if (card.energy != null) {
      const width = Math.max(0, Math.min(100, card.energy));
      html += `<div class="energyBar"><span style="width:${width}%;background-position:${100 - width}% 0"></span></div>`;
    }
    element.innerHTML = html;
    metrics.appendChild(element);
  }
}

function formatPrecise(value, digits) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "-";
}

function evasionLabel(lastTrack, lastThreat) {
  // The current state comes from the latest track sample; a fire detection alone goes stale.
  const evading = lastTrack?.fields?.evading;
  if (evading === true) return lastThreat?.normalized?.evasion || "evading";
  if (evading === false) return "none";
  return "-";
}

function renderSurfDecision() {
  const root = document.getElementById("surfCard");
  const bot = state.bots.get(state.selected);
  const decision = lastEvent(bot, "movement.option_surf");
  if (!decision) {
    root.hidden = true;
    return;
  }
  root.hidden = false;
  const fields = decision.fields || {};
  const options = [
    ["cw", "orbit clockwise", fields.danger_cw],
    ["stop", "stop", fields.danger_stop],
    ["ccw", "orbit counter-clockwise", fields.danger_ccw],
  ];
  const values = options.map(([, , value]) => (typeof value === "number" ? value : 0));
  const top = Math.max(...values, 1e-9);
  const rows = options
    .map(([key, label, value], index) => {
      const chosen = fields.option === key;
      const width = Math.max(2, (values[index] / top) * 100);
      return `<div class="surfRow${chosen ? " chosen" : ""}"><span>${chosen ? "▶ " : ""}${escapeHtml(label.replace("orbit ", ""))}</span><div class="bar"><span style="width:${width}%"></span></div><span class="num">${format(value)}</span></div>`;
    })
    .join("");
  root.innerHTML = [
    `<h3>Surf decision · turn ${escapeHtml(decision.turn ?? "-")}</h3>`,
    `<div class="hint">Danger of each option against the next ${escapeHtml(fields.waves ?? 1)} wave(s); the bot takes the lowest.</div>`,
    rows,
  ].join("");
}

function renderChart(ctx, botName, getter, minValue, maxValueOrNull, color) {
  const { width, height } = prepareCanvas(ctx);
  ctx.fillStyle = "#0e1318";
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = "rgba(255,255,255,0.05)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let line = 1; line < 4; line += 1) {
    const y = Math.round(height * line / 4) + 0.5;
    ctx.moveTo(0, y);
    ctx.lineTo(width, y);
  }
  ctx.stroke();
  const bot = state.bots.get(botName);
  if (!bot) return;
  const points = perTurnValues(bot.events, getter).slice(-240);
  if (points.length < 2) return;
  const maxValue = maxValueOrNull ?? Math.max(...points, 1);
  const coords = points.map((value, index) => {
    const x = 6 + index / Math.max(1, points.length - 1) * (width - 12);
    const normalized = (value - minValue) / Math.max(1, maxValue - minValue);
    const y = height - 8 - Math.max(0, Math.min(1, normalized)) * (height - 22);
    return [x, y];
  });
  const fill = ctx.createLinearGradient(0, 0, 0, height);
  fill.addColorStop(0, hexToRgba(color, 0.28));
  fill.addColorStop(1, hexToRgba(color, 0));
  ctx.fillStyle = fill;
  ctx.beginPath();
  ctx.moveTo(coords[0][0], height);
  for (const [x, y] of coords) ctx.lineTo(x, y);
  ctx.lineTo(coords[coords.length - 1][0], height);
  ctx.closePath();
  ctx.fill();
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.lineJoin = "round";
  ctx.beginPath();
  coords.forEach(([x, y], index) => (index === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)));
  ctx.stroke();
  const [lastX, lastY] = coords[coords.length - 1];
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.arc(lastX, lastY, 3.5, 0, Math.PI * 2);
  ctx.fill();
  ctx.font = "600 12px Inter, -apple-system, BlinkMacSystemFont, sans-serif";
  ctx.textAlign = "right";
  ctx.fillText(format(points[points.length - 1]), width - 8, 15);
  ctx.textAlign = "start";
}

function perTurnValues(events, getter) {
  // Last value per turn, in order; a new round restarts the turn counter.
  const values = [];
  let lastTurn = null;
  for (const event of events) {
    const value = getter(event);
    if (value == null) continue;
    const turn = event.turn;
    if (typeof turn === "number" && turn === lastTurn && values.length) {
      values[values.length - 1] = value;
    } else {
      values.push(value);
    }
    lastTurn = typeof turn === "number" ? turn : lastTurn;
  }
  return values;
}

function renderPerformance() {
  const root = document.getElementById("performanceGrid");
  root.replaceChildren();
  const bot = state.bots.get(state.selected);
  if (!bot) {
    root.appendChild(performanceCard("No bot selected", "-"));
    return;
  }

  const stats = buildBotStats(bot);
  const cards = [
    performanceCard("Gun Accuracy", `${stats.hits}/${stats.shots} (${percent(stats.hits, stats.shots)})`, `avg power ${format(stats.avgFirepower)}`),
    performanceCard("Damage Trade", `${format(stats.damageDealt)} dealt`, `${format(stats.damageTaken)} taken`),
    performanceCard("Energy Economy", format(stats.damagePerEnergy), `${format(stats.firepowerSpent)} firepower spent`),
    performanceCard("Threat Response", `${stats.activeEvasion}/${stats.enemyFireDetected}`, `${percent(stats.activeEvasion, stats.enemyFireDetected)} active evasion`),
    performanceCard("Collision Risk", `${stats.wallHits} wall hits`, `${stats.wallRiskHits} bullet hits near wall`),
    performanceCard("Target Control", `${stats.reacquires} reacquires`, `${stats.searchSamples} search samples`),
    performanceCard("Range", `avg ${format(stats.avgDistance)}`, `latest ${format(stats.lastDistance)}`),
    performanceCard(
      "Mode Churn",
      `${stats.gunSwitches} gun switches`,
      `${stats.gunInitialSelections} initial gun selections, ${stats.movementSwitches} movement switches`,
    ),
    performanceTable("Gun Modes", stats.gunModeRows, ["mode", "shots", "hits", "accuracy", "damage"]),
    performanceTable("Movement Modes", stats.movementModeRows, ["mode", "samples"]),
  ];

  for (const card of cards) {
    root.appendChild(card);
  }
}

function performanceCard(label, value, detail = "") {
  const card = document.createElement("div");
  card.className = "perfCard";
  card.innerHTML = [
    `<div class="label">${escapeHtml(label)}</div>`,
    `<div class="value">${escapeHtml(value ?? "-")}</div>`,
    detail ? `<div class="detail">${escapeHtml(detail)}</div>` : "",
  ].join("");
  return card;
}

function performanceTable(label, rows, columns) {
  const card = document.createElement("div");
  card.className = "perfCard perfTableCard";
  const head = columns.map((column) => `<th>${escapeHtml(column)}</th>`).join("");
  const body = rows.length
    ? rows.map((row) => `<tr>${columns.map((column) => `<td>${escapeHtml(row[column] ?? "-")}</td>`).join("")}</tr>`).join("")
    : `<tr><td colspan="${columns.length}">no data</td></tr>`;
  card.innerHTML = [
    `<div class="label">${escapeHtml(label)}</div>`,
    `<table class="miniTable"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`,
  ].join("");
  return card;
}

function buildBotStats(bot) {
  const firedBullets = new Map();
  const distances = [];
  const gunModes = new Map();
  const gunModeHits = new Map();
  const gunModeDamage = new Map();
  const movementModes = new Map();
  let previousMovementMode = null;
  const stats = {
    shots: 0,
    hits: 0,
    damageDealt: 0,
    damageTaken: 0,
    firepowerSpent: 0,
    avgFirepower: null,
    damagePerEnergy: null,
    bulletsTaken: 0,
    wallHits: 0,
    wallRiskHits: 0,
    botHits: 0,
    enemyFireDetected: 0,
    activeEvasion: 0,
    reacquires: 0,
    scanDrops: 0,
    searchSamples: 0,
    gunSwitches: 0,
    gunInitialSelections: 0,
    movementSwitches: 0,
    avgDistance: null,
    lastDistance: null,
    gunModeRows: [],
    movementModeRows: [],
  };

  for (const event of bot.events) {
    const fields = event.fields || {};
    const normalized = event.normalized || normalizeEvent(event);
    const firepower = normalized.power;
    const distance = normalized.distance;
    const movementMode = movementModeFromEvent(event);

    if (distance != null) {
      distances.push(distance);
      stats.lastDistance = distance;
    }
    if (movementMode) {
      increment(movementModes, movementMode);
      if (previousMovementMode && previousMovementMode !== movementMode) stats.movementSwitches += 1;
      previousMovementMode = movementMode;
    }

    if (event.event === "bullet.fired") {
      const mode = gunModeFromEvent(event) || "unknown";
      stats.shots += 1;
      stats.firepowerSpent += firepower ?? 0;
      increment(gunModes, mode);
      if (normalized.bulletId != null) {
        firedBullets.set(String(normalized.bulletId), mode);
      }
    } else if (event.event === "bullet.hit_bot") {
      const mode = gunModeFromEvent(event) || (normalized.bulletId != null ? firedBullets.get(String(normalized.bulletId)) : null) || "unknown";
      const damage = normalized.damage ?? 0;
      stats.hits += 1;
      stats.damageDealt += damage;
      increment(gunModeHits, mode);
      increment(gunModeDamage, mode, damage);
    } else if (event.event === "hit.bullet") {
      stats.bulletsTaken += 1;
      stats.damageTaken += normalized.damage ?? 0;
      if (normalized.wallRisk) stats.wallRiskHits += 1;
    } else if (event.event === "hit.wall") {
      stats.wallHits += 1;
    } else if (event.event === "hit.bot") {
      stats.botHits += 1;
    } else if (event.event === "enemy.fire_detected") {
      stats.enemyFireDetected += 1;
      if (normalized.evading === true) stats.activeEvasion += 1;
    } else if (event.event === "target.reacquire" || event.event === "scan.reacquired") {
      stats.reacquires += 1;
    } else if (event.event === "target.drop" || event.event === "target.drop_lost" || event.event === "target.stale" || event.event === "scan.drop") {
      stats.scanDrops += 1;
    } else if (event.event === "search") {
      stats.searchSamples += 1;
    } else if (event.event === "gun.switch") {
      if (fields.previous == null || fields.previous === "") {
        stats.gunInitialSelections += 1;
      } else if (fields.selected && fields.previous !== fields.selected) {
        stats.gunSwitches += 1;
      }
    }
  }

  stats.avgFirepower = stats.shots ? stats.firepowerSpent / stats.shots : null;
  stats.damagePerEnergy = stats.firepowerSpent > 0 ? stats.damageDealt / stats.firepowerSpent : null;
  stats.avgDistance = distances.length ? distances.reduce((total, value) => total + value, 0) / distances.length : null;
  stats.gunModeRows = rowsForGunModes(gunModes, gunModeHits, gunModeDamage);
  stats.movementModeRows = entriesByCount(movementModes, 6).map(([mode, samples]) => ({ mode, samples }));
  return stats;
}

function rowsForGunModes(gunModes, gunModeHits, gunModeDamage) {
  return entriesByCount(gunModes, 6).map(([mode, shots]) => ({
    mode,
    shots,
    hits: gunModeHits.get(mode) || 0,
    accuracy: percent(gunModeHits.get(mode) || 0, shots),
    damage: format(gunModeDamage.get(mode) || 0),
  }));
}

function renderModeTimeline(ctx, botName, modeGetter) {
  const { width: canvasWidth, height: canvasHeight } = prepareCanvas(ctx);
  const canvas = { width: canvasWidth, height: canvasHeight };
  ctx.fillStyle = "#0e1318";
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  const bot = state.bots.get(botName);
  if (!bot) return;

  const timeline = [];
  let currentMode = null;
  for (const event of bot.events) {
    const mode = modeGetter(event);
    if (mode) currentMode = mode;
    if (currentMode) timeline.push({ turn: event.turn, mode: currentMode });
  }
  const visible = timeline.slice(-320);
  if (!visible.length) return;

  const colors = colorMapForModes(visible.map((point) => point.mode));
  const top = 30;
  const height = canvas.height - top - 10;
  const width = canvas.width - 16;
  visible.forEach((point, index) => {
    const x = 8 + index / visible.length * width;
    const w = Math.max(2, Math.ceil(width / visible.length));
    ctx.fillStyle = hexToRgba(colors.get(point.mode), 0.85);
    ctx.fillRect(x, top, w, height);
  });

  let labelX = 8;
  for (const [mode, color] of colors) {
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(labelX + 5, 15, 4.5, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#c5d0da";
    ctx.font = "12px Inter, -apple-system, BlinkMacSystemFont, sans-serif";
    ctx.fillText(mode, labelX + 14, 19);
    labelX += 18 + ctx.measureText(mode).width + 14;
    if (labelX > canvas.width - 90) break;
  }
}

function colorMapForModes(modes) {
  const colors = new Map();
  for (const mode of modes) {
    if (!colors.has(mode)) {
      colors.set(mode, modePalette[colors.size % modePalette.length]);
    }
  }
  return colors;
}

function renderEvents() {
  const eventFilter = document.getElementById("eventFilter").value;
  const onlySelected = document.getElementById("onlySelected").checked;
  const showSamples = document.getElementById("showSamples").checked;
  const root = document.getElementById("events");
  root.replaceChildren();
  let events = state.events.slice(-500).reverse();
  events = events.filter((event) => eventMatchesStreamFilter(event, eventFilter));
  if (onlySelected && state.selected) {
    events = events.filter((event) => event.bot === state.selected);
  }
  if (!showSamples) {
    events = events.filter((event) => !SAMPLED_EVENTS.has(event.event));
  }
  for (const event of events.slice(0, 220)) {
    const row = document.createElement("div");
    row.className = ["event", eventClassName(event.event)].filter(Boolean).join(" ");
    const fields = summarizeEvent(event);
    row.innerHTML = [
      `<span class="turn">t${escapeHtml(event.turn ?? "-")}</span>`,
      `<span class="bot">${escapeHtml(event.bot || "-")}</span>`,
      `<span class="name">${escapeHtml(event.event || "-")}</span>`,
      `<span class="fields">${escapeHtml(fields)}</span>`,
    ].join("");
    root.appendChild(row);
  }
}

function eventClassName(eventName) {
  return eventName ? `event-${String(eventName).replaceAll(/[^a-z0-9]+/gi, "-").toLowerCase()}` : "";
}

function lastEvent(bot, name) {
  if (!bot) return null;
  for (let index = bot.events.length - 1; index >= 0; index -= 1) {
    if (bot.events[index].event === name) return bot.events[index];
  }
  return null;
}

function lastMatchingEvent(bot, predicate) {
  if (!bot) return null;
  for (let index = bot.events.length - 1; index >= 0; index -= 1) {
    if (predicate(bot.events[index])) return bot.events[index];
  }
  return null;
}

function gunList(value) {
  if (Array.isArray(value) && value.length > 0) {
    return value.join(", ");
  }
  if (typeof value === "string" && value.trim()) {
    return value;
  }
  return "-";
}

function numberAt(object, path) {
  if (!object) return null;
  const value = path.split(".").reduce((current, key) => current?.[key], object);
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function maxValue(events, path, fallback) {
  return Math.max(fallback, ...events.map((event) => numberAt(event, path)).filter((value) => value != null));
}

function increment(map, key, amount = 1) {
  map.set(key, (map.get(key) || 0) + amount);
}

function entriesByCount(map, limit) {
  return [...map.entries()].sort((left, right) => right[1] - left[1]).slice(0, limit);
}

function percent(part, whole) {
  if (!whole) return "0%";
  return `${Math.round(part / whole * 100)}%`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
