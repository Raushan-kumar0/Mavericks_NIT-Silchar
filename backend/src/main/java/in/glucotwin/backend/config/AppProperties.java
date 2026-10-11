package in.glucotwin.backend.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/** Values from the "glucotwin" block of application.yml. */
@ConfigurationProperties(prefix = "glucotwin")
public record AppProperties(
        String dataDir,
        String mlServiceUrl,
        int startDayOffset,
        int startHour,
        int minutesPerTick,
        long tickMillis,
        int windowHours,
        int twinHistoryDays,
        String frontendOrigin) {
}
