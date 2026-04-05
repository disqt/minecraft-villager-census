package com.disqt.census.events;

import java.io.BufferedWriter;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.logging.Logger;

/**
 * Thread-safe JSONL file appender. Opens file in append mode per write.
 * Creates the parent directory if it does not exist.
 */
public final class EventWriter {

    private final Path filePath;
    private final Logger logger;

    public EventWriter(Path filePath, Logger logger) {
        this.filePath = filePath;
        this.logger = logger;
    }

    /** Ensure the parent directory exists. Call once at plugin enable. */
    public void init() {
        try {
            Files.createDirectories(filePath.getParent());
        } catch (IOException e) {
            logger.warning("Failed to create events directory: " + e.getMessage());
        }
    }

    /** Append a single JSON line to the events file. */
    public synchronized void append(String json) {
        try (BufferedWriter writer = Files.newBufferedWriter(filePath,
                StandardOpenOption.CREATE, StandardOpenOption.APPEND)) {
            writer.write(json);
            writer.newLine();
        } catch (IOException e) {
            logger.warning("Failed to write event: " + e.getMessage());
        }
    }
}
