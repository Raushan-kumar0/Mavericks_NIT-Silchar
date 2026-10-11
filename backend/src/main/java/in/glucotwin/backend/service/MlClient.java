package in.glucotwin.backend.service;

import com.fasterxml.jackson.databind.JsonNode;
import in.glucotwin.backend.config.AppProperties;
import in.glucotwin.backend.model.Reading;
import in.glucotwin.backend.model.SleepNight;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

/** Thin HTTP client for the Python ML / digital-twin service. */
@Component
public class MlClient {

    private final RestClient http;

    public MlClient(RestClient.Builder builder, AppProperties props) {
        this.http = builder.baseUrl(props.mlServiceUrl()).build();
    }

    public JsonNode predict(JsonNode ehr, List<Reading> window, SleepNight lastSleep) {
        Map<String, Object> body = new HashMap<>();
        body.put("ehr", ehr);
        body.put("window", window);
        if (lastSleep != null) body.put("last_sleep", lastSleep);
        return post("/predict", body);
    }

    public JsonNode simulate(JsonNode ehr, List<Reading> history, Map<String, Object> scenario, double lastSleepHours) {
        Map<String, Object> body = new HashMap<>();
        body.put("ehr", ehr);
        body.put("history", history);
        body.put("scenario", scenario == null ? Map.of() : scenario);
        body.put("last_sleep_hours", lastSleepHours);
        return post("/twin/simulate", body);
    }

    public JsonNode calibrate(JsonNode ehr, List<Reading> history, double lastSleepHours) {
        Map<String, Object> body = new HashMap<>();
        body.put("ehr", ehr);
        body.put("history", history);
        body.put("last_sleep_hours", lastSleepHours);
        return post("/twin/calibrate", body);
    }

    public JsonNode modelInfo() {
        return http.get().uri("/model/info").retrieve().body(JsonNode.class);
    }

    private JsonNode post(String path, Object body) {
        return http.post().uri(path)
                .contentType(MediaType.APPLICATION_JSON)
                .body(body)
                .retrieve()
                .body(JsonNode.class);
    }
}
