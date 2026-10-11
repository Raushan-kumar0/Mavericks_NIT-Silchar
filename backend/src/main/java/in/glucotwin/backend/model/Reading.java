package in.glucotwin.backend.model;

import java.time.LocalDateTime;

/** One 5-minute sample from the (simulated) wearable + CGM + food-logging app. */
public record Reading(
        LocalDateTime timestamp,
        Double glucoseMgdl,
        Double heartRateBpm,
        Double hrvRmssdMs,
        int steps,
        String sleepStage,
        double carbsLoggedG) {
}
