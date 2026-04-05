package com.disqt.census.events;

import org.bukkit.entity.Entity;
import org.bukkit.entity.Villager;
import org.bukkit.event.EventHandler;
import org.bukkit.event.Listener;
import org.bukkit.event.entity.EntityBreedEvent;
import org.bukkit.event.entity.EntityDeathEvent;
import org.bukkit.event.entity.EntityDamageEvent;

import java.time.Instant;
import java.time.format.DateTimeFormatter;

public final class VillagerEventListener implements Listener {

    private static final DateTimeFormatter ISO_FMT =
            DateTimeFormatter.ISO_INSTANT;

    private final EventWriter writer;

    public VillagerEventListener(EventWriter writer) {
        this.writer = writer;
    }

    @EventHandler
    public void onBreed(EntityBreedEvent event) {
        if (!(event.getEntity() instanceof Villager child)) return;

        Entity parent1 = event.getMother();
        Entity parent2 = event.getFather();
        String timestamp = ISO_FMT.format(Instant.now());

        String json = String.format(
            "{\"type\":\"breed\",\"timestamp\":\"%s\","
            + "\"child_uuid\":\"%s\","
            + "\"parent1_uuid\":\"%s\","
            + "\"parent2_uuid\":\"%s\","
            + "\"x\":%.1f,\"y\":%.1f,\"z\":%.1f}",
            timestamp,
            child.getUniqueId(),
            parent1.getUniqueId(),
            parent2.getUniqueId(),
            child.getLocation().getX(),
            child.getLocation().getY(),
            child.getLocation().getZ()
        );

        writer.append(json);
    }

    @EventHandler
    public void onDeath(EntityDeathEvent event) {
        if (!(event.getEntity() instanceof Villager villager)) return;

        EntityDamageEvent damage = villager.getLastDamageCause();
        String cause = damage != null ? damage.getCause().name() : "UNKNOWN";

        Entity killer = event.getEntity().getKiller();
        String killerType = killer != null ? killer.getType().name() : "null";

        String timestamp = ISO_FMT.format(Instant.now());

        String json = String.format(
            "{\"type\":\"death\",\"timestamp\":\"%s\","
            + "\"uuid\":\"%s\","
            + "\"cause\":\"%s\","
            + "\"killer\":%s,"
            + "\"x\":%.1f,\"y\":%.1f,\"z\":%.1f,"
            + "\"ticks_lived\":%d}",
            timestamp,
            villager.getUniqueId(),
            cause,
            killerType.equals("null") ? "null" : "\"" + killerType + "\"",
            villager.getLocation().getX(),
            villager.getLocation().getY(),
            villager.getLocation().getZ(),
            villager.getTicksLived()
        );

        writer.append(json);
    }
}
