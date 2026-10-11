package in.glucotwin.backend.web;

import com.fasterxml.jackson.databind.JsonNode;
import in.glucotwin.backend.service.MlClient;
import in.glucotwin.backend.service.SimulationClock;
import in.glucotwin.backend.service.StreamService;
import in.glucotwin.backend.service.TwinService;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.Map;

@RestController
@RequestMapping("/api")
public class SystemController {

    private final SimulationClock clock;
    private final StreamService stream;
    private final MlClient ml;
    private final TwinService twin;

    public SystemController(SimulationClock clock, StreamService stream, MlClient ml, TwinService twin) {
        this.clock = clock;
        this.stream = stream;
        this.ml = ml;
        this.twin = twin;
    }

    public record ClockUpdate(Boolean running, Integer minutesPerTick, LocalDateTime jumpTo) {
    }

    @GetMapping("/clock")
    public Map<String, Object> clock() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("now", clock.now().toString());
        m.put("running", clock.isRunning());
        m.put("minutes_per_tick", clock.getMinutesPerTick());
        m.put("ml_up", twin.isMlUp());
        return m;
    }

    /** Pause / resume / speed up / jump the live replay (for demos). */
    @PostMapping("/clock")
    public Map<String, Object> setClock(@RequestBody ClockUpdate u) {
        clock.configure(u.running(), u.minutesPerTick(), u.jumpTo());
        return clock();
    }

    /** Model evaluation metrics, straight from the ML service. */
    @GetMapping("/model")
    public JsonNode model() {
        try {
            return ml.modelInfo();
        } catch (Exception e) {
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "ML service unavailable");
        }
    }

    /** Live updates (Server-Sent Events). */
    @GetMapping(path = "/stream", produces = "text/event-stream")
    public SseEmitter stream() {
        return stream.subscribe();
    }
}
