(function exposeTelemetryView(root) {
  function gunModeFromEvent(event) {
    if (!event) return null;
    if (event.event === "gun.switch_decision" && event.fields?.changed !== true) return null;
    return event.normalized?.gunMode || null;
  }

  function movementModeFromEvent(event) {
    if (!event) return null;
    return event.normalized?.movementMode || null;
  }

  function normalizeEvent(event) {
    const fields = event.fields || {};
    const evasion = firstValue(fields.evasion);
    const evading = fields.evading !== undefined && fields.evading !== null
      ? fields.evading
      : evasion != null ? String(evasion).startsWith("active_") : null;
    const movementMode = firstValue(fields.movement_mode, fields.mode) || movementModeFromEventName(event.event);
    const isUnchangedGunDecision = event.event === "gun.switch_decision" && fields.changed !== true;
    const gunMode = isUnchangedGunDecision ? null : firstValue(
      fields.aim_mode,
      fields.gun_mode,
      event.event === "gun.switch" ? fields.selected : null,
      event.event === "gun.switch_decision" ? fields.selected : null,
      event.event === "gun.wave_visit" ? fields.selected_gun : null,
    );
    return {
      target: firstValue(fields.target, fields.bot_id, fields.victim, event.event === "target.select" ? fields.selected : null),
      distance: numeric(firstValue(fields.distance)),
      power: numeric(firstValue(fields.power, fields.firepower)),
      damage: numeric(firstValue(fields.damage)),
      bulletId: firstValue(fields.bullet_id),
      aimMode: isUnchangedGunDecision ? null : firstValue(fields.aim_mode, gunMode),
      gunMode,
      movementMode,
      evasion,
      evading,
      wallRisk: Boolean(firstValue(fields.wall_risk, fields.near_wall)),
      reason: firstValue(fields.reason, fields.hold_reason),
      gunBearing: numeric(firstValue(fields.gun_bearing)),
    };
  }

  function movementModeFromEventName(name) {
    if (name === "movement.flatten") return "flatten";
    if (name === "movement.flatten_shadow") return "flatten_shadow";
    if (name === "movement.duel_flatten") return "duel_flatten";
    if (name === "movement.minimum_risk") return "minimum_risk";
    if (name === "movement.goto_surf") return "goto_surf";
    if (name === "movement.duel_potential") return "duel_potential";
    if (name === "wall.avoid") return "wall_avoid";
    if (name === "separate") return "separate";
    return null;
  }

  function summarizeEvent(event) {
    const fields = event.fields || {};
    if (event.event === "scan.reacquired") {
      return summarizeKeys(fields, [
        ["bot_id", "target"],
        ["previous_age", "age"],
        ["previous_x", "previous_x"],
        ["previous_y", "previous_y"],
        ["x", "current_x"],
        ["y", "current_y"],
      ]);
    }
    if (event.event === "target.stale") {
      return summarizeKeys(fields, [["bot_id", "target"], ["age", "age"]]);
    }
    if (event.event === "target.drop_lost") {
      return summarizeKeys(fields, [
        ["bot_id", "target"],
        ["age", "age"],
        ["cached_distance", "cached_distance"],
        ["known_targets", "known_targets"],
      ]);
    }
    if (event.event === "round.reset") {
      return summarizeKeys(fields, [["previous_turn", "previous_turn"], ["current_turn", "current_turn"]]);
    }
    if (event.event === "enemy.energy_drop_ignored") {
      return summarizeKeys(fields, [
        ["bot_id", "target"],
        ["reason", "reason"],
        ["corrected_drop", "drop"],
        ["raw_drop", "raw"],
        ["distance", "distance"],
        ["energy", "energy"],
      ]);
    }
    if (event.event === "telemetry.dropped") {
      return summarizeKeys(fields, [["count", "count"]]);
    }
    if (event.event === "telemetry.session") {
      return summarizeKeys(fields, [["pid", "pid"], ["queue_size", "queue_size"]]);
    }
    if (event.event === "gun.switch") {
      return summarizeKeys(fields, [["target", "target"], ["previous", "previous"], ["selected", "selected"]]);
    }
    if (event.event === "gun.switch_decision") {
      return summarizeGunSwitchDecision(fields);
    }
    return summarizeFields(fields);
  }

  function summarizeGunSwitchDecision(fields) {
    const parts = [];
    appendFieldPart(parts, fields, "target", "target");
    if (fields.changed === true) {
      const previous = format(fields.previous);
      const selected = format(fields.selected);
      parts.push(`switch=${previous}->${selected}`);
    } else {
      parts.push("switch=no");
      appendFieldPart(parts, fields, "selected", "current");
    }

    const candidates = Array.isArray(fields.candidates) ? fields.candidates : [];
    if (candidates.length > 0) {
      parts.push(formatGunSwitchCandidateCounts(candidates));
    }
    if (candidates.length > 1) {
      parts.push(`details=[${formatGunSwitchCandidateList(candidates)}]`);
    }
    return parts.length ? parts.join(" ") : summarizeFields(fields);
  }

  function formatGunSwitchCandidateCounts(candidates) {
    const counts = { selected: 0, current: 0, blocked: 0, degraded: 0, unavailable: 0, other: 0 };
    for (const candidate of candidates) {
      const status = formatCandidateStatus(candidate);
      if (status === "selected") counts.selected += 1;
      else if (status === "current") counts.current += 1;
      else if (status === "unavailable") counts.unavailable += 1;
      else if (status === "source_degraded") counts.degraded += 1;
      else if (String(status).startsWith("blocked:")) counts.blocked += 1;
      else counts.other += 1;
    }
    const parts = [];
    if (counts.selected > 0) parts.push(`selected=${counts.selected}`);
    if (counts.blocked > 0) parts.push(`blocked=${counts.blocked}`);
    if (counts.degraded > 0) parts.push(`degraded=${counts.degraded}`);
    if (counts.unavailable > 0) parts.push(`unavailable=${counts.unavailable}`);
    if (counts.other > 0) parts.push(`other=${counts.other}`);
    return parts.join(" ");
  }

  function formatGunSwitchCandidateList(candidates) {
    const maxDetails = 4;
    const visible = candidates.slice(0, maxDetails).map(formatGunSwitchCandidate);
    const hidden = candidates.length - visible.length;
    if (hidden > 0) {
      visible.push(`+${hidden} more`);
    }
    return visible.join("; ");
  }

  function formatGunSwitchCandidate(candidate) {
    const mode = format(candidate?.mode);
    const reason = formatCandidateStatus(candidate);
    const score = candidate?.score == null ? "-" : format(candidate.score);
    const parts = [`${mode} ${reason}`, `score=${score}`];
    appendVisitsPart(parts, candidate, "visits");
    appendNonZeroFieldPart(parts, candidate, "decision_bonus", "bonus");
    appendNonZeroFieldPart(parts, candidate, "eval_score_bonus", "eval");
    if (candidate?.effective_visits != null && candidate?.effective_visits !== candidate?.visits) {
      parts.push(`eff=${format(candidate.effective_visits)}`);
    }
    return parts.join(" ");
  }

  function formatCandidateStatus(candidate) {
    if (candidate?.available === false) return "unavailable";
    const reason = candidate?.reason;
    if (reason === "selected" || reason === "current" || reason === "superseded") return reason;
    if (reason === "visits" || reason === "score_floor" || reason === "margin") return `blocked:${reason}`;
    return format(reason);
  }

  function summarizeFields(fields) {
    const keys = [
      "target",
      "bot_id",
      "distance",
      "movement_mode",
      "mode",
      "aim_mode",
      "gun_mode",
      "selected",
      "power",
      "gun_bearing",
      "radar_mode",
      "evasion",
      "reason",
      "hold_reason",
      "energy",
    ];
    const parts = [];
    for (const key of keys) {
      appendFieldPart(parts, fields, key, key);
    }
    return parts.length ? parts.join(" ") : JSON.stringify(fields);
  }

  function summarizeKeys(fields, entries) {
    const parts = [];
    for (const [key, label] of entries) {
      appendFieldPart(parts, fields, key, label);
    }
    return parts.length ? parts.join(" ") : summarizeFields(fields);
  }

  function appendFieldPart(parts, fields, key, label) {
    const value = fields[key];
    if (value !== undefined && value !== null) {
      parts.push(`${label}=${format(value)}`);
    }
  }

  function appendNonZeroFieldPart(parts, fields, key, label) {
    const value = fields[key];
    if (value !== undefined && value !== null && value !== 0) {
      parts.push(`${label}=${format(value)}`);
    }
  }

  function appendVisitsPart(parts, fields, label) {
    const visits = fields?.visits;
    const required = fields?.required_visits;
    if (visits === undefined || visits === null) return;
    if (required !== undefined && required !== null) {
      parts.push(`${label}=${format(visits)}/${format(required)}`);
      return;
    }
    parts.push(`${label}=${format(visits)}`);
  }

  function displayEnergy(value) {
    const number = numeric(value);
    if (number == null) return { value: null, label: "-", dead: false };
    if (number <= 0) return { value: 0, label: "0 (dead)", dead: true };
    return { value: number, label: format(number), dead: false };
  }

  function eventMatchesStreamFilter(event, filter) {
    const name = event?.event || "";
    if (!filter || filter === "all") return true;
    if (filter === "gun") return name.startsWith("gun.");
    if (filter === "gun-switch") return name === "gun.switch" || name === "gun.switch_decision";
    if (filter === "movement") return name.startsWith("movement.") || ["wall.avoid", "separate"].includes(name);
    if (filter === "targeting") return name.startsWith("target.") || name.startsWith("scan.") || name === "search";
    if (filter === "combat") return name.startsWith("hit.") || name.startsWith("bullet.") || name.startsWith("enemy.");
    if (filter === "telemetry") return name.startsWith("telemetry.") || name === "round.reset" || name === "battle.reset";
    return true;
  }

  function numeric(value) {
    return typeof value === "number" && Number.isFinite(value) ? value : null;
  }

  function firstValue(...values) {
    for (const value of values) {
      if (value !== undefined && value !== null && value !== "") {
        return value;
      }
    }
    return null;
  }

  function format(value) {
    if (value == null) return "-";
    if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(1);
    return String(value);
  }

  const api = {
    displayEnergy,
    eventMatchesStreamFilter,
    format,
    gunModeFromEvent,
    movementModeFromEvent,
    normalizeEvent,
    summarizeEvent,
    summarizeFields,
  };

  root.TelemetryView = api;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
})(typeof window !== "undefined" ? window : globalThis);
