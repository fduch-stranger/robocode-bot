const state = {
  events: [],
  bots: new Map(),
  selected: null,
  cursor: 0,
  generation: 0,
  maxEvents: 12000,
  inactiveBotSeconds: 15,
  palette: ["#5ab0ff", "#69d391", "#f2bf62", "#ff7373", "#b68cff", "#65d6cf"],
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

const modePalette = [
  "#5ab0ff",
  "#69d391",
  "#f2bf62",
  "#ff7373",
  "#b68cff",
  "#65d6cf",
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

async function resetTelemetry() {
  if (!window.confirm("Reset telemetry stats for this viewer? Current JSONL event files will be truncated.")) {
    return;
  }
  try {
    const response = await fetch("/api/reset", { method: "POST", cache: "no-store" });
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
    state.cursor = payload.cursor || state.cursor;
    state.generation = payload.generation || state.generation;
    document.getElementById("source").textContent = `${payload.dir || ""} (${(payload.files || []).length} files)`;
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
    event.normalized = normalizeEvent(event);
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
    state.selected = state.bots.keys().next().value || null;
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
  renderTabs();
  renderArena();
  renderMetrics();
  renderChart(energyCtx, state.selected, (event) => displayEnergy(numberAt(event, "state.energy")).value, 0, 120, "#69d391");
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
    button.textContent = bot.name;
    button.className = bot.name === state.selected ? "active" : "";
    button.addEventListener("click", () => {
      state.selected = bot.name;
      render();
    });
    tabs.appendChild(button);
  }
}

function renderArena() {
  arenaCtx.clearRect(0, 0, arena.width, arena.height);
  arenaCtx.fillStyle = "#050607";
  arenaCtx.fillRect(0, 0, arena.width, arena.height);

  const latest = [...state.bots.values()].map((bot) => bot.latest).filter(Boolean);
  const width = maxValue(latest, "state.arena_width", 800);
  const height = maxValue(latest, "state.arena_height", 600);
  const pad = 28;
  const scale = Math.min((arena.width - pad * 2) / width, (arena.height - pad * 2) / height);
  const offsetX = (arena.width - width * scale) / 2;
  const offsetY = (arena.height - height * scale) / 2;

  arenaCtx.strokeStyle = "#36424d";
  arenaCtx.lineWidth = 2;
  arenaCtx.strokeRect(offsetX, offsetY, width * scale, height * scale);

  for (const bot of state.bots.values()) {
    const event = bot.latest;
    if (!event) continue;
    const x = numberAt(event, "state.x");
    const y = numberAt(event, "state.y");
    if (x == null || y == null) continue;
    const px = offsetX + x * scale;
    const py = offsetY + (height - y) * scale;
    const selected = bot.name === state.selected;

    drawVector(px, py, numberAt(event, "state.direction"), selected ? 46 : 34, bot.color, 4);
    drawVector(px, py, numberAt(event, "state.gun_direction"), selected ? 62 : 48, "#f2bf62", 3);
    drawVector(px, py, numberAt(event, "state.radar_direction"), selected ? 88 : 68, "rgba(90,176,255,0.45)", 16);

    arenaCtx.beginPath();
    arenaCtx.arc(px, py, selected ? 10 : 8, 0, Math.PI * 2);
    arenaCtx.fillStyle = bot.color;
    arenaCtx.fill();
    arenaCtx.strokeStyle = selected ? "#ffffff" : "#101315";
    arenaCtx.lineWidth = selected ? 3 : 2;
    arenaCtx.stroke();

    arenaCtx.fillStyle = "#e9eef2";
    arenaCtx.font = "12px -apple-system, BlinkMacSystemFont, sans-serif";
    arenaCtx.fillText(`${bot.name} ${displayEnergy(numberAt(event, "state.energy")).label}`, px + 12, py - 12);

    const targetX = numberAt(event, "fields.predicted_x");
    const targetY = numberAt(event, "fields.predicted_y");
    if (selected && targetX != null && targetY != null) {
      const tx = offsetX + targetX * scale;
      const ty = offsetY + (height - targetY) * scale;
      arenaCtx.strokeStyle = "rgba(242,191,98,0.75)";
      arenaCtx.setLineDash([5, 4]);
      arenaCtx.beginPath();
      arenaCtx.moveTo(px, py);
      arenaCtx.lineTo(tx, ty);
      arenaCtx.stroke();
      arenaCtx.setLineDash([]);
      arenaCtx.fillStyle = "#f2bf62";
      arenaCtx.fillRect(tx - 4, ty - 4, 8, 8);
    }
  }
}

function drawVector(x, y, degrees, length, color, width) {
  if (degrees == null) return;
  const radians = degrees * Math.PI / 180;
  arenaCtx.strokeStyle = color;
  arenaCtx.lineWidth = width;
  arenaCtx.beginPath();
  arenaCtx.moveTo(x, y);
  arenaCtx.lineTo(x + Math.cos(radians) * length, y - Math.sin(radians) * length);
  arenaCtx.stroke();
}

function renderMetrics() {
  document.getElementById("selectedBot").textContent = state.selected || "none";
  const metrics = document.getElementById("metrics");
  metrics.replaceChildren();
  const bot = state.bots.get(state.selected);
  const latest = bot?.latest;
  const lastFire = lastEvent(bot, "bullet.fired");
  const lastGunSwitch = lastEvent(bot, "gun.switch");
  const lastAim = lastMatchingEvent(bot, (event) => event.normalized?.gunBearing != null || gunModeFromEvent(event));
  const lastTarget = lastMatchingEvent(bot, (event) => event.normalized?.target != null);
  const lastDistance = lastMatchingEvent(bot, (event) => event.normalized?.distance != null);
  const lastMovement = lastMatchingEvent(bot, (event) => event.normalized?.movementMode);
  const lastThreat = lastEvent(bot, "enemy.fire_detected");
  const botConfig = lastEvent(bot, "bot.config");

  const cards = [
    ["Turn", latest?.turn],
    ["Energy", displayEnergy(numberAt(latest, "state.energy")).label],
    ["Position", latest ? `${format(numberAt(latest, "state.x"))}, ${format(numberAt(latest, "state.y"))}` : "-"],
    ["Target", lastTarget?.normalized?.target ?? "-"],
    ["Movement", movementModeFromEvent(lastMovement) || "-"],
    ["Evasion", latest?.normalized?.evading ?? lastThreat?.normalized?.evasion ?? "-"],
    ["Gun", gunModeFromEvent(lastAim) || gunModeFromEvent(lastFire) || lastGunSwitch?.fields?.selected || "-"],
    ["Live Guns", gunList(botConfig?.fields?.selectable_guns)],
    ["Pinned Gun", botConfig?.fields?.forced_gun || "-"],
    ["Gun Bearing Error", format(lastAim?.normalized?.gunBearing)],
    ["Firepower", format(lastFire?.normalized?.power)],
    ["Gun Confidence", format(lastFire?.fields?.gun_confidence)],
    ["Distance", format(lastDistance?.normalized?.distance)],
    ["Last Event", latest?.event || "-"],
  ];
  for (const [label, value] of cards) {
    const card = document.createElement("div");
    card.className = "metric";
    card.innerHTML = `<div class="label">${escapeHtml(label)}</div><div class="value">${escapeHtml(value ?? "-")}</div>`;
    metrics.appendChild(card);
  }
}

function renderChart(ctx, botName, getter, minValue, maxValueOrNull, color) {
  const canvas = ctx.canvas;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#111518";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.strokeStyle = "#36424d";
  ctx.strokeRect(0, 0, canvas.width, canvas.height);
  const bot = state.bots.get(botName);
  if (!bot) return;
  const points = bot.events.map(getter).filter((value) => value != null);
  if (points.length < 2) return;
  const maxValue = maxValueOrNull ?? Math.max(...points, 1);
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.beginPath();
  points.slice(-240).forEach((value, index, visible) => {
    const x = 8 + index / Math.max(1, visible.length - 1) * (canvas.width - 16);
    const normalized = (value - minValue) / Math.max(1, maxValue - minValue);
    const y = canvas.height - 8 - Math.max(0, Math.min(1, normalized)) * (canvas.height - 16);
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
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
  const canvas = ctx.canvas;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#111518";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.strokeStyle = "#36424d";
  ctx.strokeRect(0, 0, canvas.width, canvas.height);

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
    ctx.fillStyle = colors.get(point.mode);
    ctx.fillRect(x, top, w, height);
  });

  let labelX = 8;
  for (const [mode, color] of colors) {
    ctx.fillStyle = color;
    ctx.fillRect(labelX, 10, 10, 10);
    ctx.fillStyle = "#cbd5dc";
    ctx.font = "12px -apple-system, BlinkMacSystemFont, sans-serif";
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
    events = events.filter((event) => !["track", "search", "movement.duel_potential"].includes(event.event));
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
