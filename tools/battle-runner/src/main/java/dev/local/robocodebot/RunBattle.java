package dev.local.robocodebot;

import dev.robocode.tankroyale.runner.BattleRunner;
import dev.robocode.tankroyale.runner.BattleSetup;
import dev.robocode.tankroyale.runner.BotEntry;
import dev.robocode.tankroyale.runner.BotResult;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;

public final class RunBattle {
    private RunBattle() {
    }

    public static void main(String[] args) {
        var options = BattleOptions.parse(args);
        if (options.botDirs().size() < 2) {
            throw new IllegalArgumentException(
                    "Usage: RunBattle [--rounds N] [--results FILE] <bot-dir> <bot-dir> [bot-dir...]"
            );
        }

        List<BotEntry> bots = options.botDirs().stream()
                .map(BotEntry::of)
                .toList();

        try (var runner = BattleRunner.create(builder -> {
            builder.embeddedServer();
            builder.botConnectTimeout(Duration.ofSeconds(20));
        })) {
            var botCount = bots.size();
            var setup = bots.size() == 2
                    ? BattleSetup.oneVsOne(builder -> builder.setNumberOfRounds(options.rounds()))
                    : BattleSetup.melee(builder -> {
                        builder.setMinNumberOfParticipants(botCount);
                        builder.setMaxNumberOfParticipants(botCount);
                        builder.setNumberOfRounds(options.rounds());
                    });

            var results = runner.runBattle(
                    setup,
                    bots
            );

            System.out.println("Battle results:");
            results.getResults().forEach(bot ->
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

            if (options.resultsPath() != null) {
                writeResults(options.resultsPath(), setup, options.botDirs(), results.getResults());
                System.out.println("Wrote battle results: " + options.resultsPath());
            }
        }
    }

    private static void writeResults(
            Path resultsPath,
            BattleSetup setup,
            List<String> botDirs,
            List<BotResult> results
    ) {
        try {
            var parent = resultsPath.toAbsolutePath().getParent();
            if (parent != null) {
                Files.createDirectories(parent);
            }
            Files.writeString(resultsPath, toJson(setup, botDirs, results), StandardCharsets.UTF_8);
        } catch (IOException exception) {
            throw new IllegalStateException("Failed to write battle results to " + resultsPath, exception);
        }
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
        return value
                .replace("\\", "\\\\")
                .replace("\"", "\\\"")
                .replace("\n", "\\n")
                .replace("\r", "\\r")
                .replace("\t", "\\t");
    }

    private record BattleOptions(int rounds, Path resultsPath, List<String> botDirs) {
        static BattleOptions parse(String[] args) {
            var rounds = 3;
            Path resultsPath = null;
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
                    default -> botDirs.add(args[i]);
                }
            }

            return new BattleOptions(rounds, resultsPath, botDirs);
        }
    }
}
