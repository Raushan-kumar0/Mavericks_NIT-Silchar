package in.glucotwin.backend.service;

import com.fasterxml.jackson.databind.JsonNode;
import in.glucotwin.backend.model.Alert;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.time.LocalDateTime;
import java.util.*;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Turns twin predictions into doctor-facing alerts.
 * Rule: raise an alert when P(spike within 2 h) crosses the model threshold,
 * at most once per patient per 2 hours of simulated time (avoids alarm fatigue).
 */
@Service
public class AlertService {

    private static final Duration COOLDOWN = Duration.ofHours(2);

    private final List<Alert> alerts = new CopyOnWriteArrayList<>();
    private final Map<String, LocalDateTime> lastAlertAt = new HashMap<>();
    private final AtomicLong ids = new AtomicLong(1);

    public synchronized Optional<Alert> evaluate(String patientId, String patientName, JsonNode pred, LocalDateTime now) {
        String level = pred.path("risk_level").asText("LOW");
        if (!level.equals("HIGH") && !level.equals("MODERATE")) return Optional.empty();

        LocalDateTime last = lastAlertAt.get(patientId);
        if (last != null && now.isAfter(last) && Duration.between(last, now).compareTo(COOLDOWN) < 0) {
            return Optional.empty();
        }
        if (last != null && now.isBefore(last)) {
            lastAlertAt.remove(patientId); // clock looped back
        }

        double p = pred.path("spike_probability_2h").asDouble();
        JsonNode peak = pred.path("expected_peak");
        double peakG = peak.path("glucose").asDouble();
        int peakMin = peak.path("minutes_ahead").asInt();

        List<String> drivers = new ArrayList<>();
        for (JsonNode d : pred.path("drivers")) {
            if ("raises risk".equals(d.path("effect").asText())) drivers.add(d.path("label").asText());
            if (drivers.size() == 3) break;
        }
        String msg = String.format("%.0f%% chance glucose crosses 180 mg/dL within 2 h (now %.0f mg/dL, forecast %.0f in %d min).",
                Math.min(99.0, p * 100), pred.path("current_glucose").asDouble(), peakG, peakMin);

        Alert a = new Alert(ids.getAndIncrement(), patientId, patientName, now, level, p, peakG, peakMin, msg, drivers);
        alerts.add(0, a);
        lastAlertAt.put(patientId, now);
        if (alerts.size() > 500) alerts.remove(alerts.size() - 1);
        return Optional.of(a);
    }

    public List<Alert> list(boolean openOnly, String patientId) {
        return alerts.stream()
                .filter(a -> !openOnly || !a.isAcknowledged())
                .filter(a -> patientId == null || a.getPatientId().equals(patientId))
                .toList();
    }

    public long openCount(String patientId) {
        return alerts.stream().filter(a -> !a.isAcknowledged() && a.getPatientId().equals(patientId)).count();
    }

    public Optional<Alert> acknowledge(long id, String note) {
        Optional<Alert> a = alerts.stream().filter(x -> x.getId() == id).findFirst();
        a.ifPresent(x -> x.acknowledge(note));
        return a;
    }
}
