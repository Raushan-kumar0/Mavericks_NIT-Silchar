package in.glucotwin.backend.service;

import com.fasterxml.jackson.databind.JsonNode;
import in.glucotwin.backend.config.AppProperties;
import in.glucotwin.backend.data.DataStore;
import in.glucotwin.backend.model.Alert;
import in.glucotwin.backend.model.PatientSummary;
import in.glucotwin.backend.model.Reading;
import in.glucotwin.backend.model.SleepNight;
import jakarta.annotation.PreDestroy;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.time.LocalDateTime;
import java.util.*;
import java.util.concurrent.*;

/**
 * Keeps every patient's digital twin up to date.
 * On every clock tick: fuse the patient's EHR with the latest wearable window,
 * ask the ML service for a 2-hour forecast, raise alerts, and push the update to dashboards.
 */
@Service
public class TwinService {

    private static final Logger log = LoggerFactory.getLogger(TwinService.class);

    private final DataStore store;
    private final SimulationClock clock;
    private final MlClient ml;
    private final AlertService alerts;
    private final StreamService stream;
    private final AppProperties props;
    private final Map<String, JsonNode> latest = new ConcurrentHashMap<>();
    private final ExecutorService pool = Executors.newFixedThreadPool(8);
    private volatile boolean mlUp = true;

    public TwinService(DataStore store, SimulationClock clock, MlClient ml, AlertService alerts,
                       StreamService stream, AppProperties props) {
        this.store = store;
        this.clock = clock;
        this.ml = ml;
        this.alerts = alerts;
        this.stream = stream;
        this.props = props;
    }

    @Scheduled(fixedDelayString = "${glucotwin.tick-millis:3000}", initialDelay = 2000)
    public void tick() {
        boolean moved = clock.advance();
        if (!moved && !latest.isEmpty()) {
            stream.broadcast("tick", Map.of("now", clock.now().toString(), "running", false));
            return;
        }
        LocalDateTime now = clock.now();
        List<Alert> fresh = Collections.synchronizedList(new ArrayList<>());
        List<Future<?>> jobs = new ArrayList<>();
        for (String id : store.patientIds()) {
            jobs.add(pool.submit(() -> {
                JsonNode p = predictNow(id, now);
                if (p != null) {
                    alerts.evaluate(id, name(id), p, now).ifPresent(fresh::add);
                }
            }));
        }
        for (Future<?> f : jobs) {
            try {
                f.get(30, TimeUnit.SECONDS);
            } catch (Exception e) {
                log.debug("prediction job failed: {}", e.getMessage());
            }
        }
        Map<String, Object> event = new LinkedHashMap<>();
        event.put("now", now.toString());
        event.put("running", clock.isRunning());
        event.put("ml_up", mlUp);
        event.put("new_alerts", fresh);
        stream.broadcast("tick", event);
    }

    /** Fuse EHR + wearable window and ask the ML service for a prediction. */
    public JsonNode predictNow(String id, LocalDateTime now) {
        JsonNode ehr = store.ehr(id).orElseThrow();
        List<Reading> window = store.window(id, now, Duration.ofHours(props.windowHours()));
        if (window.size() < 36) return null;
        SleepNight sleep = store.lastSleep(id, now).orElse(null);
        try {
            JsonNode p = ml.predict(ehr, window, sleep);
            latest.put(id, p);
            if (!mlUp) log.info("ML service reachable again");
            mlUp = true;
            return p;
        } catch (Exception e) {
            if (mlUp) log.warn("ML service not reachable at {}: {}", props.mlServiceUrl(), e.getMessage());
            mlUp = false;
            return null;
        }
    }

    public JsonNode prediction(String id) {
        JsonNode p = latest.get(id);
        return p != null ? p : predictNow(id, clock.now());
    }

    public JsonNode whatIf(String id, Map<String, Object> scenario) {
        LocalDateTime now = clock.now();
        JsonNode ehr = store.ehr(id).orElseThrow();
        List<Reading> hist = store.window(id, now, Duration.ofDays(props.twinHistoryDays()));
        double sleep = store.lastSleep(id, now).map(SleepNight::sleepHours).orElse(7.0);
        return ml.simulate(ehr, hist, scenario, sleep);
    }

    public JsonNode calibration(String id) {
        LocalDateTime now = clock.now();
        JsonNode ehr = store.ehr(id).orElseThrow();
        List<Reading> hist = store.window(id, now, Duration.ofDays(props.twinHistoryDays()));
        double sleep = store.lastSleep(id, now).map(SleepNight::sleepHours).orElse(7.0);
        return ml.calibrate(ehr, hist, sleep);
    }

    public PatientSummary summary(String id) {
        JsonNode e = store.ehr(id).orElseThrow();
        LocalDateTime now = clock.now();
        List<Reading> day = store.window(id, now, Duration.ofHours(24));
        long valid = day.stream().filter(r -> r.glucoseMgdl() != null).count();
        long inRange = day.stream().filter(r -> r.glucoseMgdl() != null && r.glucoseMgdl() >= 70 && r.glucoseMgdl() <= 180).count();
        Double current = store.latest(id, now).map(Reading::glucoseMgdl).orElse(null);
        JsonNode p = latest.get(id);
        return new PatientSummary(
                id,
                e.path("name").asText(),
                e.path("age").asInt(),
                e.path("gender").asText(),
                e.path("address").path("city").asText(),
                e.path("labs").path("hba1c_pct").isMissingNode() ? null : e.path("labs").path("hba1c_pct").asDouble(),
                p != null ? p.path("current_glucose").asDouble() : current,
                p != null && p.hasNonNull("trend_mgdl_per_15min") ? p.get("trend_mgdl_per_15min").asDouble() : null,
                p != null ? p.path("spike_probability_2h").asDouble() : null,
                p != null ? p.path("risk_level").asText() : "UNKNOWN",
                p != null ? p.path("expected_peak").path("glucose").asDouble() : null,
                valid == 0 ? null : Math.round(1000.0 * inRange / valid) / 10.0,
                alerts.openCount(id));
    }

    public List<PatientSummary> summaries() {
        List<PatientSummary> list = new ArrayList<>(store.patientIds().stream().map(this::summary).toList());
        list.sort(Comparator.comparingInt((PatientSummary s) -> rank(s.riskLevel()))
                .thenComparingDouble(s -> -Optional.ofNullable(s.spikeProbability()).orElse(0.0)));
        return list;
    }

    private static int rank(String level) {
        return switch (level) {
            case "ACTIVE_SPIKE" -> 1;
            case "HIGH" -> 0;
            case "MODERATE" -> 2;
            case "LOW" -> 3;
            default -> 4;
        };
    }

    private String name(String id) {
        return store.ehr(id).map(e -> e.path("name").asText()).orElse(id);
    }

    public boolean isMlUp() { return mlUp; }

    @PreDestroy
    void shutdown() {
        pool.shutdownNow();
    }
}
