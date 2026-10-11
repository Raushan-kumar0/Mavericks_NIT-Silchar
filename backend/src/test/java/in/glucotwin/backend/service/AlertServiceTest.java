package in.glucotwin.backend.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import java.time.LocalDateTime;

import static org.junit.jupiter.api.Assertions.*;

class AlertServiceTest {

    private final ObjectMapper om = new ObjectMapper();

    private JsonNode pred(String level, double p) throws Exception {
        return om.readTree("{\"risk_level\":\"" + level + "\",\"spike_probability_2h\":" + p
                + ",\"current_glucose\":150,\"expected_peak\":{\"glucose\":205,\"minutes_ahead\":90},"
                + "\"drivers\":[{\"label\":\"carbs logged (last 1 h)\",\"effect\":\"raises risk\"}]}");
    }

    @Test
    void raisesAlertOnHighRiskAndRespectsCooldown() throws Exception {
        AlertService s = new AlertService();
        LocalDateTime t = LocalDateTime.of(2026, 9, 8, 13, 0);
        assertTrue(s.evaluate("GT-001", "A", pred("HIGH", 0.82), t).isPresent());
        assertTrue(s.evaluate("GT-001", "A", pred("HIGH", 0.9), t.plusMinutes(30)).isEmpty(), "cooldown");
        assertTrue(s.evaluate("GT-001", "A", pred("HIGH", 0.9), t.plusHours(3)).isPresent());
        assertEquals(2, s.openCount("GT-001"));
    }

    @Test
    void ignoresLowRisk() throws Exception {
        AlertService s = new AlertService();
        assertTrue(s.evaluate("GT-002", "B", pred("LOW", 0.1), LocalDateTime.now()).isEmpty());
    }
}
