package in.glucotwin.backend.data;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import in.glucotwin.backend.config.AppProperties;
import in.glucotwin.backend.model.Reading;
import in.glucotwin.backend.model.SleepNight;
import jakarta.annotation.PostConstruct;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.io.BufferedReader;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.time.LocalDateTime;
import java.util.*;

/**
 * Loads the two data streams produced by data-generator/generate.py:
 *   - static EHR records (ehr_patients.json)
 *   - dynamic wearable time series (wearable_timeseries.csv) + nightly sleep (sleep_summary.csv)
 * Readings are on a fixed 5-minute grid, so a timestamp maps directly to a list index.
 */
@Component
public class DataStore {

    private static final Logger log = LoggerFactory.getLogger(DataStore.class);
    public static final int STEP_MINUTES = 5;

    private final AppProperties props;
    private final ObjectMapper mapper;

    private final Map<String, JsonNode> ehr = new LinkedHashMap<>();
    private final Map<String, List<Reading>> readings = new HashMap<>();
    private final Map<String, List<SleepNight>> sleep = new HashMap<>();
    private LocalDateTime dataStart;
    private LocalDateTime dataEnd;

    public DataStore(AppProperties props, ObjectMapper mapper) {
        this.props = props;
        this.mapper = mapper;
    }

    @PostConstruct
    void load() throws IOException {
        Path dir = Path.of(props.dataDir());
        log.info("Loading GlucoTwin data from {}", dir.toAbsolutePath());

        JsonNode arr = mapper.readTree(dir.resolve("ehr_patients.json").toFile());
        for (JsonNode p : arr) {
            ehr.put(p.get("id").asText(), p);
        }

        try (BufferedReader br = Files.newBufferedReader(dir.resolve("wearable_timeseries.csv"))) {
            Map<String, Integer> col = header(br.readLine());
            String line;
            while ((line = br.readLine()) != null) {
                String[] f = line.split(",", -1);
                Reading r = new Reading(
                        LocalDateTime.parse(f[col.get("timestamp")]),
                        num(f[col.get("glucose_mgdl")]),
                        num(f[col.get("heart_rate_bpm")]),
                        num(f[col.get("hrv_rmssd_ms")]),
                        (int) Math.round(Optional.ofNullable(num(f[col.get("steps")])).orElse(0.0)),
                        f[col.get("sleep_stage")],
                        Optional.ofNullable(num(f[col.get("carbs_logged_g")])).orElse(0.0));
                readings.computeIfAbsent(f[col.get("patient_id")], k -> new ArrayList<>()).add(r);
            }
        }
        readings.values().forEach(l -> l.sort(Comparator.comparing(Reading::timestamp)));

        try (BufferedReader br = Files.newBufferedReader(dir.resolve("sleep_summary.csv"))) {
            Map<String, Integer> col = header(br.readLine());
            String line;
            while ((line = br.readLine()) != null) {
                String[] f = line.split(",", -1);
                Double awak = num(f[col.get("awakenings")]);
                SleepNight s = new SleepNight(
                        LocalDateTime.parse(f[col.get("wake_time")]),
                        Optional.ofNullable(num(f[col.get("sleep_hours")])).orElse(7.0),
                        num(f[col.get("deep_pct")]),
                        num(f[col.get("rem_pct")]),
                        awak == null ? null : awak.intValue(),
                        num(f[col.get("night_hrv_ms")]),
                        num(f[col.get("night_rhr_bpm")]));
                sleep.computeIfAbsent(f[col.get("patient_id")], k -> new ArrayList<>()).add(s);
            }
        }
        sleep.values().forEach(l -> l.sort(Comparator.comparing(SleepNight::wakeTime)));

        List<Reading> any = readings.values().iterator().next();
        dataStart = any.get(0).timestamp();
        dataEnd = any.get(any.size() - 1).timestamp();
        log.info("Loaded {} patients, {} readings each, {} -> {}", ehr.size(), any.size(), dataStart, dataEnd);
    }

    private static Map<String, Integer> header(String line) {
        Map<String, Integer> m = new HashMap<>();
        String[] h = line.split(",");
        for (int i = 0; i < h.length; i++) m.put(h[i].trim(), i);
        return m;
    }

    private static Double num(String s) {
        if (s == null || s.isBlank() || s.equalsIgnoreCase("nan")) return null;
        return Double.parseDouble(s);
    }

    public Collection<String> patientIds() { return ehr.keySet(); }
    public Optional<JsonNode> ehr(String id) { return Optional.ofNullable(ehr.get(id)); }
    public LocalDateTime dataStart() { return dataStart; }
    public LocalDateTime dataEnd() { return dataEnd; }

    /** Readings in (to - duration, to], i.e. everything the twin is allowed to "know" at time {@code to}. */
    public List<Reading> window(String id, LocalDateTime to, Duration duration) {
        List<Reading> all = readings.getOrDefault(id, List.of());
        if (all.isEmpty()) return List.of();
        int end = indexOf(to) + 1;
        int start = end - (int) (duration.toMinutes() / STEP_MINUTES);
        start = Math.max(0, start);
        end = Math.min(all.size(), Math.max(end, 0));
        return start >= end ? List.of() : all.subList(start, end);
    }

    public Optional<Reading> latest(String id, LocalDateTime now) {
        List<Reading> w = window(id, now, Duration.ofMinutes(STEP_MINUTES));
        return w.isEmpty() ? Optional.empty() : Optional.of(w.get(w.size() - 1));
    }

    /** Most recent completed night of sleep at time {@code now}. */
    public Optional<SleepNight> lastSleep(String id, LocalDateTime now) {
        SleepNight best = null;
        for (SleepNight s : sleep.getOrDefault(id, List.of())) {
            if (!s.wakeTime().isAfter(now)) best = s;
        }
        return Optional.ofNullable(best);
    }

    public List<SleepNight> sleepHistory(String id, LocalDateTime now, int nights) {
        List<SleepNight> done = sleep.getOrDefault(id, List.of()).stream()
                .filter(s -> !s.wakeTime().isAfter(now)).toList();
        return done.subList(Math.max(0, done.size() - nights), done.size());
    }

    private int indexOf(LocalDateTime t) {
        return (int) (Duration.between(dataStart, t).toMinutes() / STEP_MINUTES);
    }
}
