package com.disqt.census.events;

import org.bukkit.plugin.java.JavaPlugin;

import java.nio.file.Path;

public final class VillagerCensusEventsPlugin extends JavaPlugin {

    @Override
    public void onEnable() {
        Path eventsFile = getDataFolder().toPath().resolve("events.jsonl");
        EventWriter writer = new EventWriter(eventsFile, getLogger());
        writer.init();

        getServer().getPluginManager().registerEvents(
                new VillagerEventListener(writer), this);

        getLogger().info("VillagerCensusEvents enabled -- writing to " + eventsFile);
    }
}
