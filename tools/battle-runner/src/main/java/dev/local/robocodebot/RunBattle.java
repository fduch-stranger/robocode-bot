package dev.local.robocodebot;

import dev.robocode.tankroyale.client.model.TickEvent;
import dev.robocode.tankroyale.intent.CapturedIntent;
import dev.robocode.tankroyale.runner.BattleRunner;
import dev.robocode.tankroyale.runner.BattleSetup;
import dev.robocode.tankroyale.runner.BotEntry;
import dev.robocode.tankroyale.runner.BotResult;

import java.io.IOException;
import java.io.PrintWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.atomic.AtomicInteger;

public final class RunBattle {
    private RunBattle() {
    }

    public static void main(String[] args) {
        var options = BattleOptions.parse(args);
        if (options.botDirs().size() < 2) {
            throw new IllegalArgumentException(
                    "Usage: RunBattle [--rounds N] [--results FILE] [--runner-log FILE] [--record DIR] "
                            + "[--intent-diagnostics] [--intents FILE] [--tick-sample N] <bot-dir> <bot-dir> [bot-dir...]"
            );
        }

        List<BotEntry> bots = options.botDirs().stream()
                .map(BotEntry::of)
                .toList();

        createParentDirectories(options);

        try (
                var log = openLog(options.runnerLogPath());
                var runner = BattleRunner.create(builder -> {
                    builder.embeddedServer();
                    builder.botConnectTimeout(Duration.ofSeconds(20));
                    if (options.recordPath() != null) {
                        builder.enableRecording(options.recordPath());
                    }
                    if (options.intentDiagnostics()) {
                        builder.enableIntentDiagnostics();
                    }
                })
        ) {
            var botCount = bots.size();
            var setup = bots.size() == 2
                    ? BattleSetup.oneVsOne(builder -> builder.setNumberOfRounds(options.rounds()))
                    : BattleSetup.melee(builder -> {
                        builder.setMinNumberOfParticipants(botCount);
                        builder.setMaxNumberOfParticipants(botCount);
                        builder.setNumberOfRounds(options.rounds());
                    });

            log(log, "run.start", "rounds", setup.getNumberOfRounds(), "gameType", setup.getGameType(),
                    "bots", botCount, "recording", options.recordPath() != null,
                    "intentDiagnostics", options.intentDiagnostics());
            options.botDirs().forEach(botDir -> log(log, "bot.dir", "path", botDir));
            if (options.recordPath() != null) {
                log(log, "recording.path", "path", options.recordPath());
            }
            if (options.resultsPath() != null) {
                log(log, "results.path", "path", options.resultsPath());
            }
            if (options.intentsPath() != null) {
                log(log, "intents.path", "path", options.intentsPath());
            }

            try {
                var handle = runner.startBattleAsync(setup, bots);
                attachEventLogs(handle, log, options.tickSample());

                var results = handle.awaitResults();
                handle.close();

                log(log, "run.finished", "results", results.getResults().size());
                printResults(results.getResults());

                if (options.resultsPath() != null) {
                    writeResults(options.resultsPath(), setup, options.botDirs(), results.getResults());
                    System.out.println("Wrote battle results: " + options.resultsPath());
                    log(log, "results.written", "path", options.resultsPath());
                }

                if (options.intentDiagnostics() && options.intentsPath() != null) {
                    var count = writeIntents(options.intentsPath(), runner.getIntentDiagnostics().getAllIntents());
                    log(log, "intents.written", "path", options.intentsPath(), "count", count);
                    System.out.println("Wrote intent diagnostics: " + options.intentsPath());
                }
            } catch (RuntimeException exception) {
                log(log, "run.failed", "type", exception.getClass().getName(), "message", exception.getMessage());
                throw exception;
            }
        }
    }

    private static void attachEventLogs(
            dev.robocode.tankroyale.runner.BattleHandle handle,
            PrintWriter log,
            int tickSample
    ) {
        handle.getOnBootProgress().on(RunBattle.class, progress ->
                log(log, "boot.progress", "connected", progress.getTotalConnected(), "expected",
                        progress.getTotalExpected(), "elapsedMs", progress.getElapsedMs(),
                        "timeoutMs", progress.getTimeoutMs()));
        handle.getOnGameStarted().on(RunBattle.class, event ->
                log(log, "game.started", "participants", event.getParticipants().size()));
        handle.getOnRoundStarted().on(RunBattle.class, event ->
                log(log, "round.started", "round", event.getRoundNumber()));
        handle.getOnRoundEnded().on(RunBattle.class, event -> {
            log(log, "round.ended", "round", event.getRoundNumber(), "turn", event.getTurnNumber(),
                    "results", event.getResults().size());
            event.getResults().forEach(result -> log(log, "round.result",
                    "round", event.getRoundNumber(),
                    "rank", result.getRank(),
                    "name", token(result.getName()),
                    "score", result.getTotalScore(),
                    "survival", result.getSurvival(),
                    "bulletDamage", result.getBulletDamage(),
                    "ramDamage", result.getRamDamage(),
                    "firstPlaces", result.getFirstPlaces()));
        });
        handle.getOnGameEnded().on(RunBattle.class, event ->
                log(log, "game.ended", "rounds", event.getNumberOfRounds(), "results", event.getResults().size()));
        handle.getOnGameAborted().on(RunBattle.class, event ->
                log(log, "game.aborted", "event", event.getClass().getSimpleName()));

        if (tickSample > 0) {
            var ticks = new AtomicInteger();
            handle.getOnTickEvent().on(RunBattle.class, event -> logTick(log, event, tickSample, ticks));
        }
    }

    private static void logTick(PrintWriter log, TickEvent event, int tickSample, AtomicInteger ticks) {
        var count = ticks.incrementAndGet();
        if (count % tickSample != 0) {
            return;
        }
        log(log, "tick", "round", event.getRoundNumber(), "turn", event.getTurnNumber(),
                "bots", event.getBotStates().size(), "bullets", event.getBulletStates().size(),
                "events", event.getEvents().size());
        event.getBotStates().stream()
                .sorted((left, right) -> Integer.compare(left.getId(), right.getId()))
                .forEach(bot -> log(log, "bot.state",
                        "round", event.getRoundNumber(),
                        "turn", event.getTurnNumber(),
                        "id", bot.getId(),
                        "name", token(bot.getName()),
                        "energy", decimal(bot.getEnergy()),
                        "x", decimal(bot.getX()),
                        "y", decimal(bot.getY()),
                        "direction", decimal(bot.getDirection()),
                        "gunDirection", decimal(bot.getGunDirection()),
                        "radarDirection", decimal(bot.getRadarDirection()),
                        "speed", decimal(bot.getSpeed()),
                        "turnRate", decimal(bot.getTurnRate()),
                        "gunTurnRate", decimal(bot.getGunTurnRate()),
                        "radarTurnRate", decimal(bot.getRadarTurnRate()),
                        "gunHeat", decimal(bot.getGunHeat()),
                        "enemyCount", bot.getEnemyCount()));
        event.getEvents().forEach(tickEvent -> log(log, "tick.event",
                "round", event.getRoundNumber(),
                "turn", event.getTurnNumber(),
                "type", tickEvent.getClass().getSimpleName()));
    }

    private static void printResults(List<BotResult> results) {
        System.out.println("Battle results:");
        results.forEach(bot ->
                System.out.printf(
                        "#%d %s %s score=%d survival=%d bulletDamage=%d ramDamage=%d firstPlaces=%d%n",
                        bot.getRank(),
                        bot.getName(),
                        bot.getVersion(),
                        bot.getTotalScore(),
                        bot.getSurvival(),
                        bot.getBulletDamage(),
                        bot.getRamDamage(),
                        bot.getFirstPlaces()
                )
        );
    }

    private static void createParentDirectories(BattleOptions options) {
        createParentDirectory(options.resultsPath());
        createParentDirectory(options.runnerLogPath());
        createDirectory(options.recordPath());
        createParentDirectory(options.intentsPath());
    }

    private static void createDirectory(Path path) {
        if (path == null) {
            return;
        }
        try {
            Files.createDirectories(path);
        } catch (IOException exception) {
            throw new IllegalStateException("Failed to create directory " + path, exception);
        }
    }

    private static void createParentDirectory(Path path) {
        if (path == null) {
            return;
        }
        try {
            var parent = path.toAbsolutePath().getParent();
            if (parent != null) {
                Files.createDirectories(parent);
            }
        } catch (IOException exception) {
            throw new IllegalStateException("Failed to create parent directory for " + path, exception);
        }
    }

    private static PrintWriter openLog(Path runnerLogPath) {
        if (runnerLogPath == null) {
            return new PrintWriter(System.err, true);
        }
        try {
            return new PrintWriter(Files.newBufferedWriter(runnerLogPath, StandardCharsets.UTF_8), true);
        } catch (IOException exception) {
            throw new IllegalStateException("Failed to open runner log " + runnerLogPath, exception);
        }
    }

    private static void log(PrintWriter log, String event, Object... fields) {
        log.print("at=");
        log.print(Instant.now());
        log.print(" event=");
        log.print(event);
        for (var i = 0; i + 1 < fields.length; i += 2) {
            log.print(' ');
            log.print(fields[i]);
            log.print('=');
            log.print(fields[i + 1]);
        }
        log.println();
    }

    private static void writeResults(
            Path resultsPath,
            BattleSetup setup,
            List<String> botDirs,
            List<BotResult> results
    ) {
        try {
            Files.writeString(resultsPath, toJson(setup, botDirs, results), StandardCharsets.UTF_8);
        } catch (IOException exception) {
            throw new IllegalStateException("Failed to write battle results to " + resultsPath, exception);
        }
    }

    private static int writeIntents(
            Path intentsPath,
            java.util.Map<String, List<CapturedIntent>> intentsByBot
    ) {
        var count = 0;
        try (var writer = Files.newBufferedWriter(intentsPath, StandardCharsets.UTF_8)) {
            for (var intents : intentsByBot.values()) {
                for (var intent : intents) {
                    writer.write(intentToJson(intent));
                    writer.newLine();
                    count++;
                }
            }
        } catch (IOException exception) {
            throw new IllegalStateException("Failed to write intent diagnostics to " + intentsPath, exception);
        }
        return count;
    }

    private static String intentToJson(CapturedIntent captured) {
        var intent = captured.getIntent();
        return "{"
                + "\"botName\":\"" + escape(captured.getBotName()) + "\","
                + "\"botVersion\":\"" + escape(captured.getBotVersion()) + "\","
                + "\"round\":" + captured.getRoundNumber() + ","
                + "\"turn\":" + captured.getTurnNumber() + ","
                + "\"turnRate\":" + nullable(intent.getTurnRate()) + ","
                + "\"gunTurnRate\":" + nullable(intent.getGunTurnRate()) + ","
                + "\"radarTurnRate\":" + nullable(intent.getRadarTurnRate()) + ","
                + "\"targetSpeed\":" + nullable(intent.getTargetSpeed()) + ","
                + "\"firepower\":" + nullable(intent.getFirepower()) + ","
                + "\"rescan\":" + nullable(intent.getRescan()) + ","
                + "\"fireAssist\":" + nullable(intent.getFireAssist()) + ","
                + "\"stdout\":\"" + escape(trim(intent.getStdOut())) + "\","
                + "\"stderr\":\"" + escape(trim(intent.getStdErr())) + "\""
                + "}";
    }

    private static String nullable(Object value) {
        return value == null ? "null" : value.toString();
    }

    private static String decimal(double value) {
        return String.format(Locale.ROOT, "%.2f", value);
    }

    private static String token(String value) {
        if (value == null) {
            return "";
        }
        return value.trim().replaceAll("\\s+", "_");
    }

    private static String trim(String value) {
        if (value == null) {
            return "";
        }
        return value.length() <= 300 ? value : value.substring(0, 300);
    }

    private static String toJson(
            BattleSetup setup,
            List<String> botDirs,
            List<BotResult> results
    ) {
        var json = new StringBuilder();
        json.append("{\n");
        json.append("  \"createdAt\": \"").append(escape(Instant.now().toString())).append("\",\n");
        json.append("  \"gameType\": \"").append(escape(setup.getGameType().toString())).append("\",\n");
        json.append("  \"rounds\": ").append(setup.getNumberOfRounds()).append(",\n");
        json.append("  \"botDirs\": [\n");
        for (var i = 0; i < botDirs.size(); i++) {
            json.append("    \"").append(escape(botDirs.get(i))).append("\"");
            json.append(i + 1 == botDirs.size() ? "\n" : ",\n");
        }
        json.append("  ],\n");
        json.append("  \"results\": [\n");
        for (var i = 0; i < results.size(); i++) {
            var bot = results.get(i);
            json.append("    {\n");
            json.append("      \"rank\": ").append(bot.getRank()).append(",\n");
            json.append("      \"name\": \"").append(escape(bot.getName())).append("\",\n");
            json.append("      \"version\": \"").append(escape(bot.getVersion())).append("\",\n");
            json.append("      \"totalScore\": ").append(bot.getTotalScore()).append(",\n");
            json.append("      \"survival\": ").append(bot.getSurvival()).append(",\n");
            json.append("      \"bulletDamage\": ").append(bot.getBulletDamage()).append(",\n");
            json.append("      \"ramDamage\": ").append(bot.getRamDamage()).append(",\n");
            json.append("      \"firstPlaces\": ").append(bot.getFirstPlaces()).append("\n");
            json.append("    }").append(i + 1 == results.size() ? "\n" : ",\n");
        }
        json.append("  ]\n");
        json.append("}\n");
        return json.toString();
    }

    private static String escape(String value) {
        if (value == null) {
            return "";
        }
        return value
                .replace("\\", "\\\\")
                .replace("\"", "\\\"")
                .replace("\n", "\\n")
                .replace("\r", "\\r")
                .replace("\t", "\\t");
    }

    private record BattleOptions(
            int rounds,
            Path resultsPath,
            Path runnerLogPath,
            Path recordPath,
            boolean intentDiagnostics,
            Path intentsPath,
            int tickSample,
            List<String> botDirs
    ) {
        static BattleOptions parse(String[] args) {
            var rounds = 3;
            Path resultsPath = null;
            Path runnerLogPath = null;
            Path recordPath = null;
            var intentDiagnostics = false;
            Path intentsPath = null;
            var tickSample = 0;
            var botDirs = new ArrayList<String>();

            for (var i = 0; i < args.length; i++) {
                switch (args[i]) {
                    case "--rounds" -> {
                        if (++i >= args.length) {
                            throw new IllegalArgumentException("--rounds requires a value");
                        }
                        rounds = Integer.parseInt(args[i]);
                        if (rounds < 1) {
                            throw new IllegalArgumentException("--rounds must be positive");
                        }
                    }
                    case "--results" -> {
                        if (++i >= args.length) {
                            throw new IllegalArgumentException("--results requires a value");
                        }
                        resultsPath = Path.of(args[i]);
                    }
                    case "--runner-log" -> {
                        if (++i >= args.length) {
                            throw new IllegalArgumentException("--runner-log requires a value");
                        }
                        runnerLogPath = Path.of(args[i]);
                    }
                    case "--record" -> {
                        if (++i >= args.length) {
                            throw new IllegalArgumentException("--record requires a value");
                        }
                        recordPath = Path.of(args[i]);
                    }
                    case "--intent-diagnostics" -> intentDiagnostics = true;
                    case "--intents" -> {
                        if (++i >= args.length) {
                            throw new IllegalArgumentException("--intents requires a value");
                        }
                        intentsPath = Path.of(args[i]);
                    }
                    case "--tick-sample" -> {
                        if (++i >= args.length) {
                            throw new IllegalArgumentException("--tick-sample requires a value");
                        }
                        tickSample = Integer.parseInt(args[i]);
                        if (tickSample < 0) {
                            throw new IllegalArgumentException("--tick-sample must be non-negative");
                        }
                    }
                    default -> botDirs.add(args[i]);
                }
            }

            return new BattleOptions(rounds, resultsPath, runnerLogPath, recordPath, intentDiagnostics,
                    intentsPath, tickSample, botDirs);
        }
    }
}
