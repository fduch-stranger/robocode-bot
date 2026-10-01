#!/usr/bin/env python3
"""Render a Tank Royale battle recording (``.battle.gz``) to an animated GIF.

Record a battle with ``scripts/run-battle.sh --record ...``, then:

    tools/render_battle_gif.py battle-results/runs/<run>/recordings/<game>.battle.gz \
        --output docs/assets/battle.gif --round 1 --start 120 --turns 360

Requires Pillow (``.venv/bin/pip install pillow``) and ``ffmpeg`` on PATH for
palette-optimized output; without ffmpeg Pillow writes the GIF itself.
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import shutil
import subprocess
import sys
import tempfile
from collections import deque
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover - optional dependency
    sys.exit("Pillow is required: .venv/bin/pip install pillow")

BACKGROUND = (13, 17, 23)
ARENA = (22, 27, 34)
GRID = (33, 39, 48)
BORDER = (68, 76, 86)
TEXT = (230, 237, 243)
MUTED = (139, 148, 158)
HIT = (255, 120, 80)
SPARK = (255, 220, 120)
DODGE = (90, 220, 255)
TRAIL_LENGTH = 40
BULLET_TAIL = 3
# A bullet that passes this close to a bot's centre without hitting is a near
# miss: the hit circle is 18 px, so this is within about a body width.
MISS_DISTANCE = 40.0


def hex_color(value: str | None, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
    if not value or not value.startswith("#") or len(value) < 7:
        return fallback
    return tuple(int(value[i : i + 2], 16) for i in (1, 3, 5))


def readable(color: tuple[int, int, int], minimum: int = 90) -> tuple[int, int, int]:
    """Lift very dark bot colors so they stay visible on the dark arena."""
    brightness = max(color)
    if brightness >= minimum:
        return color
    if brightness == 0:
        return (minimum, minimum, minimum)
    scale = minimum / brightness
    return tuple(min(255, int(c * scale)) for c in color)


def load_rounds(path: Path) -> tuple[dict, dict[int, list[dict]]]:
    setup: dict = {}
    rounds: dict[int, list[dict]] = {}
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            kind = record.get("type")
            if kind == "GameStartedEventForObserver":
                setup = record
            elif kind == "TickEventForObserver":
                rounds.setdefault(record.get("roundNumber"), []).append(record)
    return setup, rounds


def bullet_tracks(ticks: list[dict]) -> dict[int, dict]:
    """Per bullet: wave origin, speed, first turn, whether it hit, and its closest pass."""
    tracks: dict[int, dict] = {}
    for tick in ticks:
        turn = tick["turnNumber"]
        bots = tick.get("botStates", [])
        for event in tick.get("events", []):
            if event.get("type") in ("BulletHitBotEvent", "BulletHitBulletEvent"):
                bullet_id = event["bullet"]["bulletId"]
                tracks.setdefault(bullet_id, {"seed": event["bullet"], "turn": turn})["hit"] = True
        for bullet in tick.get("bulletStates", []):
            track = tracks.get(bullet["bulletId"])
            if track is None or "origin" not in track:
                speed = 20.0 - 3.0 * bullet.get("power", 1.0)
                heading = math.radians(bullet["direction"])
                # A bullet is first seen one step out from its gun.
                track = tracks.setdefault(bullet["bulletId"], {})
                track.update(
                    origin=(bullet["x"] - math.cos(heading) * speed, bullet["y"] - math.sin(heading) * speed),
                    speed=speed,
                    first_turn=turn,
                    owner=bullet["ownerId"],
                    closest=(math.inf, turn, None, None),
                )
            for bot in bots:
                if bot["id"] == bullet["ownerId"]:
                    continue
                distance = math.hypot(bullet["x"] - bot["x"], bullet["y"] - bot["y"])
                if distance < track["closest"][0]:
                    track["closest"] = (distance, turn, (bullet["x"], bullet["y"]), bot["id"])
    for track in tracks.values():
        closest = track.get("closest", (math.inf, 0, None, None))
        track["near_miss"] = not track.get("hit") and closest[0] < MISS_DISTANCE
    return tracks


def best_dodge_window(rounds: dict[int, list[dict]], turns: int) -> tuple[int, int, int, int]:
    """Round and start turn with the most near misses, fewest hits and most energy left."""
    best = None
    for round_number, ticks in rounds.items():
        tracks = bullet_tracks(ticks)
        misses = [t["closest"][1] for t in tracks.values() if t["near_miss"]]
        hits = [tick["turnNumber"] for tick in ticks for e in tick.get("events", []) if e.get("type") == "BulletHitBotEvent"]
        energy = {tick["turnNumber"]: min(b["energy"] for b in tick["botStates"]) for tick in ticks if tick.get("botStates")}
        last = ticks[-1]["turnNumber"]
        for start in range(30, max(31, last - turns), 10):
            window_misses = sum(1 for turn in misses if start <= turn < start + turns)
            window_hits = sum(1 for turn in hits if start <= turn < start + turns)
            low_energy = energy.get(start + turns // 2, 0.0)
            score = window_misses - 1.0 * window_hits + low_energy / 25.0
            if best is None or score > best[0]:
                best = (score, round_number, start, window_misses, window_hits)
    assert best is not None
    return best[1], best[2], best[3], best[4]


def font(size: int):
    for candidate in ("/System/Library/Fonts/SFNSMono.ttf", "/System/Library/Fonts/Menlo.ttc", "DejaVuSansMono.ttf"):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


class Renderer:
    def __init__(self, setup: dict, scale: float, tracks: dict[int, dict] | None = None, waves: bool = True) -> None:
        game = setup.get("gameSetup", {})
        self.arena_width = float(game.get("arenaWidth", 800))
        self.arena_height = float(game.get("arenaHeight", 600))
        self.scale = scale
        self.margin = 16
        self.header = 62
        self.width = int(self.arena_width * scale) + 2 * self.margin
        self.height = int(self.arena_height * scale) + self.header + self.margin
        self.names = {p["id"]: p["name"] for p in setup.get("participants", [])}
        self.trails: dict[int, deque] = {}
        self.bullet_tails: dict[int, deque] = {}
        self.blasts: list[list] = []
        self.hit_flash: dict[int, int] = {}
        self.tracks = tracks or {}
        self.waves = waves
        self.misses_by_turn: dict[int, list[dict]] = {}
        for track in self.tracks.values():
            if track.get("near_miss"):
                self.misses_by_turn.setdefault(track["closest"][1], []).append(track)
        self.dodges: list[list] = []
        self.dodge_count = 0
        self.font = font(14)
        self.small = font(11)

    def to_image(self, x: float, y: float) -> tuple[float, float]:
        return self.margin + x * self.scale, self.header + (self.arena_height - y) * self.scale

    def draw(self, tick: dict, caption: str) -> Image.Image:
        image = Image.new("RGB", (self.width, self.height), BACKGROUND)
        draw = ImageDraw.Draw(image, "RGBA")
        left, top = self.to_image(0, self.arena_height)
        right, bottom = self.to_image(self.arena_width, 0)
        draw.rectangle([left, top, right, bottom], fill=ARENA, outline=BORDER, width=2)
        for gx in range(100, int(self.arena_width), 100):
            x, _ = self.to_image(gx, 0)
            draw.line([x, top + 1, x, bottom - 1], fill=GRID)
        for gy in range(100, int(self.arena_height), 100):
            _, y = self.to_image(0, gy)
            draw.line([left + 1, y, right - 1, y], fill=GRID)

        bots = tick.get("botStates", [])
        accents = {bot["id"]: readable(hex_color(bot.get("bulletColor"), SPARK), 140) for bot in bots}
        bodies = {bot["id"]: hex_color(bot.get("bodyColor"), (120, 160, 220)) for bot in bots}
        # A near-black body is drawn dark with its accent as the identifying color.
        colors = {bot_id: (accents[bot_id] if max(body) < 70 else readable(body)) for bot_id, body in bodies.items()}

        for event in tick.get("events", []):
            if event.get("type") == "BulletHitBotEvent":
                bullet = event["bullet"]
                self.blasts.append([bullet["x"], bullet["y"], 0, HIT])
                self.hit_flash[event["victimId"]] = 6
            elif event.get("type") == "BulletHitBulletEvent":
                bullet = event["bullet"]
                self.blasts.append([bullet["x"], bullet["y"], 0, SPARK])
            elif event.get("type") == "BotDeathEvent":
                victim = next((b for b in bots if b["id"] == event["victimId"]), None)
                if victim is not None:
                    self.blasts.append([victim["x"], victim["y"], -6, HIT])

        turn = tick.get("turnNumber", 0)
        if self.waves:
            for bullet in tick.get("bulletStates", []):
                track = self.tracks.get(bullet["bulletId"])
                if not track or "origin" not in track:
                    continue
                world_radius = track["speed"] * (turn - track["first_turn"] + 1)
                # Brighten the wave as it closes on the nearest opponent: that is the one being dodged.
                gaps = [
                    math.hypot(bot["x"] - track["origin"][0], bot["y"] - track["origin"][1]) - world_radius
                    for bot in bots
                    if bot["id"] != track["owner"]
                ]
                gap = min(gaps) if gaps else 200.0
                if gap < -30:
                    alpha = 20
                else:
                    alpha = int(25 + 150 * max(0.0, min(1.0, 1.0 - gap / 160.0)))
                radius = world_radius * self.scale
                ox, oy = self.to_image(*track["origin"])
                color = colors.get(track["owner"], SPARK)
                draw.ellipse([ox - radius, oy - radius, ox + radius, oy + radius], outline=(*color, alpha), width=2 if alpha > 120 else 1)

        for track in self.misses_by_turn.get(turn, []):
            point = track["closest"][2]
            self.dodges.append([point[0], point[1], 0, track["closest"][3], max(0.0, track["closest"][0] - 18.0)])
            self.dodge_count += 1

        for bot in bots:
            trail = self.trails.setdefault(bot["id"], deque(maxlen=TRAIL_LENGTH))
            trail.append(self.to_image(bot["x"], bot["y"]))
            points = list(trail)
            color = colors[bot["id"]]
            for index in range(1, len(points)):
                alpha = int(150 * index / len(points))
                draw.line([points[index - 1], points[index]], fill=(*color, alpha), width=2)

        live_ids = set()
        for bullet in tick.get("bulletStates", []):
            live_ids.add(bullet["bulletId"])
            tail = self.bullet_tails.setdefault(bullet["bulletId"], deque(maxlen=BULLET_TAIL))
            tail.append(self.to_image(bullet["x"], bullet["y"]))
            color = accents.get(bullet["ownerId"], SPARK)
            points = list(tail)
            for index in range(1, len(points)):
                draw.line([points[index - 1], points[index]], fill=(*color, 110), width=2)
            x, y = points[-1]
            radius = 1.5 + bullet.get("power", 1.0) * 0.9
            draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=color)
        for bullet_id in list(self.bullet_tails):
            if bullet_id not in live_ids:
                del self.bullet_tails[bullet_id]

        for bot in bots:
            self._draw_tank(draw, bot, bodies[bot["id"]], colors[bot["id"]], accents[bot["id"]])

        remaining = []
        for blast in self.blasts:
            x, y, age, color = blast
            if age >= 0:
                cx, cy = self.to_image(x, y)
                radius = 4 + age * 3.2
                alpha = max(0, 230 - age * 28)
                draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], outline=(*color, alpha), width=3)
            blast[2] += 1
            if blast[2] < 9:
                remaining.append(blast)
        self.blasts = remaining

        positions = {bot["id"]: bot for bot in bots}
        remaining = []
        for dodge in self.dodges:
            x, y, age, victim, gap = dodge
            cx, cy = self.to_image(x, y)
            alpha = max(0, 255 - age * 16)
            radius = 3 + age * 0.8
            draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], outline=(*DODGE, alpha), width=2)
            bot = positions.get(victim)
            if bot is not None:
                bx, by = self.to_image(bot["x"], bot["y"])
                label = f"dodged by {gap:.0f} px"
                label_x = bx + 22
                if label_x + draw.textlength(label, font=self.font) > right - 4:
                    label_x = bx - 22 - draw.textlength(label, font=self.font)
                label_y = max(top + 4, by - 34 - age * 1.2)
                draw.text((label_x, label_y), label, fill=(*DODGE, alpha), font=self.font)
            dodge[2] += 1
            if dodge[2] < 16:
                remaining.append(dodge)
        self.dodges = remaining

        # Waves may extend past the arena; repaint the frame around it.
        draw.rectangle([0, 0, self.width, top - 1], fill=BACKGROUND)
        draw.rectangle([0, bottom + 1, self.width, self.height], fill=BACKGROUND)
        draw.rectangle([0, top, left - 1, bottom], fill=BACKGROUND)
        draw.rectangle([right + 1, top, self.width, bottom], fill=BACKGROUND)
        draw.rectangle([left, top, right, bottom], outline=BORDER, width=2)

        title, _, status = caption.partition("|")
        draw.text((self.margin, 10), title.strip(), fill=TEXT, font=self.font)
        status = status.strip()
        if self.dodge_count:
            status = f"dodges {self.dodge_count}   {status}"
        draw.text((self.width - self.margin - draw.textlength(status, font=self.small), 12), status, fill=MUTED, font=self.small)
        x = float(self.margin)
        for bot in sorted(bots, key=lambda b: b["id"]):
            color = colors[bot["id"]]
            draw.rectangle([x, 37, x + 10, 47], fill=color)
            label = f"{self.names.get(bot['id'], bot.get('name', '?'))}  {bot['energy']:5.1f}"
            draw.text((x + 16, 34), label, fill=color, font=self.font)
            x += 16 + draw.textlength(label, font=self.font) + 28
        return image

    def _draw_tank(self, draw: ImageDraw.ImageDraw, bot: dict, body, color, accent) -> None:
        cx, cy = self.to_image(bot["x"], bot["y"])
        half = 18 * self.scale
        heading = math.radians(bot.get("direction", 0.0))
        cos_h, sin_h = math.cos(heading), -math.sin(heading)
        corners = []
        for dx, dy in ((half, half * 0.8), (half, -half * 0.8), (-half, -half * 0.8), (-half, half * 0.8)):
            corners.append((cx + dx * cos_h - dy * sin_h, cy + dx * sin_h + dy * cos_h))
        fill = readable(body, 40) if max(body) < 70 else color
        draw.polygon(corners, fill=(*fill, 245), outline=(*color, 255), width=2)
        gun = math.radians(bot.get("gunDirection", 0.0))
        gun_length = 26 * self.scale
        draw.line([cx, cy, cx + math.cos(gun) * gun_length, cy - math.sin(gun) * gun_length], fill=accent, width=3)
        draw.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], fill=accent)
        radar = math.radians(bot.get("radarDirection", 0.0))
        radar_length = 60 * self.scale
        draw.line([cx, cy, cx + math.cos(radar) * radar_length, cy - math.sin(radar) * radar_length], fill=(*accent, 70), width=1)
        energy = max(0.0, min(100.0, bot.get("energy", 0.0)))
        flash = self.hit_flash.get(bot["id"], 0)
        bar_width = 64 * self.scale
        bar_top = cy - half - 16
        bar_color = HIT if flash > 0 else color
        draw.rectangle([cx - bar_width / 2 - 1, bar_top - 1, cx + bar_width / 2 + 1, bar_top + 7], fill=(48, 54, 61))
        draw.rectangle([cx - bar_width / 2, bar_top, cx - bar_width / 2 + bar_width * energy / 100.0, bar_top + 6], fill=bar_color)
        label = f"{energy:.0f}"
        draw.text((cx - draw.textlength(label, font=self.small) / 2, bar_top - 15), label, fill=bar_color, font=self.small)
        if flash > 0:
            self.hit_flash[bot["id"]] = flash - 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("recording", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--round", type=int, default=1, help="Round number to render (1-based).")
    parser.add_argument("--start", type=int, default=1, help="First turn to render.")
    parser.add_argument("--turns", type=int, default=300, help="Number of turns to render.")
    parser.add_argument("--step", type=int, default=2, help="Render every Nth turn.")
    parser.add_argument("--fps", type=int, default=25)
    parser.add_argument("--scale", type=float, default=0.8)
    parser.add_argument("--title", default=None, help="Caption prefix; defaults to the participant names.")
    parser.add_argument("--auto-window", action="store_true", help="Pick the round and start with the most near misses (overrides --round and --start).")
    parser.add_argument("--no-waves", action="store_true", help="Do not draw bullet waves.")
    args = parser.parse_args()

    setup, rounds = load_rounds(args.recording)
    if args.auto_window:
        args.round, args.start, misses, hits = best_dodge_window(rounds, args.turns)
        print(f"Auto window: round {args.round}, turns {args.start}-{args.start + args.turns - 1}, {misses} near misses, {hits} hits")
    ticks = rounds.get(args.round, [])
    if not ticks:
        print(f"No ticks found for round {args.round}", file=sys.stderr)
        return 1
    renderer = Renderer(setup, args.scale, bullet_tracks(ticks), waves=not args.no_waves)
    title = args.title or " vs ".join(p["name"] for p in setup.get("participants", []))
    selected = [t for t in ticks if args.start <= t["turnNumber"] < args.start + args.turns]
    frames: list[Image.Image] = []
    # Events between rendered frames still trigger blasts.
    pending_events: list[dict] = []
    for index, tick in enumerate(selected):
        pending_events.extend(tick.get("events", []))
        if index % args.step:
            continue
        merged = dict(tick)
        merged["events"] = pending_events
        pending_events = []
        frames.append(renderer.draw(merged, f"{title} | round {args.round} · turn {tick['turnNumber']}"))
    if not frames:
        print("No frames in the selected window", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if shutil.which("ffmpeg"):
        with tempfile.TemporaryDirectory() as tmp:
            for index, frame in enumerate(frames):
                frame.save(Path(tmp) / f"f{index:05d}.png")
            pattern = str(Path(tmp) / "f%05d.png")
            palette = str(Path(tmp) / "palette.png")
            subprocess.run(
                ["ffmpeg", "-loglevel", "error", "-y", "-framerate", str(args.fps), "-i", pattern, "-vf", "palettegen=max_colors=128:stats_mode=diff", palette],
                check=True,
            )
            subprocess.run(
                [
                    "ffmpeg", "-loglevel", "error", "-y", "-framerate", str(args.fps), "-i", pattern, "-i", palette,
                    "-lavfi", "paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle", "-loop", "0", str(args.output),
                ],
                check=True,
            )
    else:
        frames[0].save(args.output, save_all=True, append_images=frames[1:], duration=int(1000 / args.fps), loop=0, optimize=True)
    print(f"Wrote {args.output} ({len(frames)} frames, {args.output.stat().st_size / 1024:.0f} KiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
