package in.glucotwin.backend.web;

import in.glucotwin.backend.model.Alert;
import in.glucotwin.backend.service.AlertService;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/alerts")
public class AlertController {

    private final AlertService alerts;

    public AlertController(AlertService alerts) {
        this.alerts = alerts;
    }

    @GetMapping
    public List<Alert> list(@RequestParam(defaultValue = "false") boolean open,
                            @RequestParam(required = false) String patient) {
        return alerts.list(open, patient);
    }

    /** Doctor acknowledges an alert, optionally with an action note. */
    @PostMapping("/{id}/ack")
    public Alert acknowledge(@PathVariable long id, @RequestBody(required = false) Map<String, String> body) {
        String note = body == null ? null : body.get("note");
        return alerts.acknowledge(id, note)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "No alert " + id));
    }
}
