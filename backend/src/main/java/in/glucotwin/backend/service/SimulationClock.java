package in.glucotwin.backend.service;

import in.glucotwin.backend.config.AppProperties;
import in.glucotwin.backend.data.DataStore;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;

/**
 * Replays the recorded sensor data as if it were arriving live.
 * The twin can only "see" readings up to {@link #now()}.
 */
@Component
public class SimulationClock {

    private final DataStore store;
    private volatile LocalDateTime now;
    private volatile boolean running = true;
    private volatile int minutesPerTick;

    public SimulationClock(DataStore store, AppProperties props) {
        this.store = store;
        this.minutesPerTick = props.minutesPerTick();
        this.now = store.dataStart().plusDays(props.startDayOffset()).plusHours(props.startHour());
    }

    public LocalDateTime now() { return now; }
    public boolean isRunning() { return running; }
    public int getMinutesPerTick() { return minutesPerTick; }

    public synchronized boolean advance() {
        if (!running) return false;
        LocalDateTime next = now.plusMinutes(minutesPerTick);
        if (next.isAfter(store.dataEnd().minusHours(3))) {
            // loop back so a long demo never runs out of data
            next = store.dataStart().plusDays(2);
        }
        now = next;
        return true;
    }

    public synchronized void configure(Boolean run, Integer speed, LocalDateTime jumpTo) {
        if (run != null) running = run;
        if (speed != null) minutesPerTick = Math.max(DataStore.STEP_MINUTES, (speed / DataStore.STEP_MINUTES) * DataStore.STEP_MINUTES);
        if (jumpTo != null) {
            LocalDateTime min = store.dataStart().plusDays(1);
            LocalDateTime max = store.dataEnd().minusHours(3);
            now = jumpTo.isBefore(min) ? min : (jumpTo.isAfter(max) ? max : jumpTo);
            // keep on the 5-minute grid
            now = now.withSecond(0).withNano(0).withMinute((now.getMinute() / 5) * 5);
        }
    }
}
