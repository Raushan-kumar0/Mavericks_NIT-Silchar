package in.glucotwin.backend.model;

import java.time.LocalDateTime;

/** Nightly sleep summary produced by the wearable. */
public record SleepNight(
        LocalDateTime wakeTime,
        double sleepHours,
        Double deepPct,
        Double remPct,
        Integer awakenings,
        Double nightHrvMs,
        Double nightRhrBpm) {
}
