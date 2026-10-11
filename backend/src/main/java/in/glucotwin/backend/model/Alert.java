package in.glucotwin.backend.model;

import java.time.LocalDateTime;
import java.util.List;

/** A predictive alert raised by the twin before a glucose spike happens. */
public class Alert {
    private final long id;
    private final String patientId;
    private final String patientName;
    private final LocalDateTime createdAt;
    private final String severity;          // HIGH or MODERATE
    private final double probability;
    private final double expectedPeak;
    private final int peakInMinutes;
    private final String message;
    private final List<String> drivers;
    private boolean acknowledged;
    private String acknowledgedNote;

    public Alert(long id, String patientId, String patientName, LocalDateTime createdAt, String severity,
                 double probability, double expectedPeak, int peakInMinutes, String message, List<String> drivers) {
        this.id = id;
        this.patientId = patientId;
        this.patientName = patientName;
        this.createdAt = createdAt;
        this.severity = severity;
        this.probability = probability;
        this.expectedPeak = expectedPeak;
        this.peakInMinutes = peakInMinutes;
        this.message = message;
        this.drivers = drivers;
    }

    public long getId() { return id; }
    public String getPatientId() { return patientId; }
    public String getPatientName() { return patientName; }
    public LocalDateTime getCreatedAt() { return createdAt; }
    public String getSeverity() { return severity; }
    public double getProbability() { return probability; }
    public double getExpectedPeak() { return expectedPeak; }
    public int getPeakInMinutes() { return peakInMinutes; }
    public String getMessage() { return message; }
    public List<String> getDrivers() { return drivers; }
    public boolean isAcknowledged() { return acknowledged; }
    public String getAcknowledgedNote() { return acknowledgedNote; }

    public void acknowledge(String note) {
        this.acknowledged = true;
        this.acknowledgedNote = note;
    }
}
