package in.glucotwin.backend.model;

/** One row of the doctor's patient list. */
public record PatientSummary(
        String id,
        String name,
        int age,
        String gender,
        String city,
        Double hba1c,
        Double currentGlucose,
        Double trendPerQuarterHour,
        Double spikeProbability,
        String riskLevel,
        Double expectedPeak,
        Double timeInRangeDay,
        long openAlerts) {
}
