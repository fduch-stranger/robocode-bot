package dev.local.robocodebot;

import dev.robocode.tankroyale.runner.BattleRunner;
import dev.robocode.tankroyale.runner.BattleSetup;
import dev.robocode.tankroyale.runner.BotEntry;

import java.time.Duration;
import java.util.Arrays;
import java.util.List;

public final class RunBattle {
    private RunBattle() {
    }

    public static void main(String[] args) {
        if (args.length < 2) {
            throw new IllegalArgumentException("Usage: RunBattle <bot-dir> <bot-dir> [bot-dir...]");
        }

        List<BotEntry> bots = Arrays.stream(args)
                .map(BotEntry::of)
                .toList();

        try (var runner = BattleRunner.create(builder -> {
            builder.embeddedServer();
            builder.botConnectTimeout(Duration.ofSeconds(20));
        })) {
            var botCount = bots.size();
            var setup = bots.size() == 2
                    ? BattleSetup.oneVsOne(builder -> builder.setNumberOfRounds(3))
                    : BattleSetup.melee(builder -> {
                        builder.setMinNumberOfParticipants(botCount);
                        builder.setMaxNumberOfParticipants(botCount);
                        builder.setNumberOfRounds(3);
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
        }
    }
}
