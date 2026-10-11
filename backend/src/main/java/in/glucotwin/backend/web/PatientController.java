package in.glucotwin.backend.web;

import com.fasterxml.jackson.databind.JsonNode;
import in.glucotwin.backend.data.DataStore;
import in.glucotwin.backend.model.PatientSummary;
import in.glucotwin.backend.model.Reading;
import in.glucotwin.backend.service.SimulationClock;
import in.glucotwin.backend.service.TwinService;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/patients")
public class PatientController {

    private final DataStore store;
    private final TwinService twin;
    private final SimulationClock clock;

    public PatientController(DataStore store, TwinService twin, SimulationClock clock) {
        this.store = store;
        this.twin = twin;
        this.clock = clock;
    }

    /** Patient list for the doctor, highest risk first. */
    @GetMapping
    public List<PatientSummary> list() {
        return twin.summaries();
    }

    /** Static EHR + summary + recent sleep for one patient. */
    @GetMapping("/{id}")
    public Map<String, Object> detail(@PathVariable String id) {
        JsonNode ehr = store.ehr(id).orElseThrow(() -> notFound(id));
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("ehr", ehr);
        m.put("summary", twin.summary(id));
        m.put("sleep_history", store.sleepHistory(id, clock.now(), 7));
        return m;
    }

    /** Wearable + CGM readings up to the current (simulated) time. */
    @GetMapping("/{id}/timeline")
    public List<Reading> timeline(@PathVariable String id, @RequestParam(defaultValue = "24") int hours) {
        store.ehr(id).orElseThrow(() -> notFound(id));
        int h = Math.max(1, Math.min(hours, 24 * 7));
        return store.window(id, clock.now(), Duration.ofHours(h));
    }

    /** Latest 2-hour forecast and spike risk from the ML model. */
    @GetMapping("/{id}/prediction")
    public JsonNode prediction(@PathVariable String id) {
        store.ehr(id).orElseThrow(() -> notFound(id));
        JsonNode p = twin.prediction(id);
        if (p == null) throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "ML service unavailable");
        return p;
    }

    /** Personalised physiology parameters of the twin (calibrated on recent CGM + meal logs). */
    @GetMapping("/{id}/twin")
    public JsonNode calibration(@PathVariable String id) {
        store.ehr(id).orElseThrow(() -> notFound(id));
        return wrap(() -> twin.calibration(id));
    }

    /**
     * What-if simulation on the patient's twin. Example body:
     * {"carb_change_pct": {"dinner": -30}, "post_meal_walk_min": {"lunch": 20},
     *  "dinner_shift_h": -1.5, "sleep_hours": 7.5, "morning_walk_min": 30}
     */
    @PostMapping("/{id}/whatif")
    public JsonNode whatIf(@PathVariable String id, @RequestBody(required = false) Map<String, Object> scenario) {
        store.ehr(id).orElseThrow(() -> notFound(id));
        return wrap(() -> twin.whatIf(id, scenario == null ? Map.of() : scenario));
    }

    private static JsonNode wrap(java.util.function.Supplier<JsonNode> call) {
        try {
            return call.get();
        } catch (Exception e) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "ML service error: " + e.getMessage());
        }
    }

    private static ResponseStatusException notFound(String id) {
        return new ResponseStatusException(HttpStatus.NOT_FOUND, "No patient " + id);
    }
}
