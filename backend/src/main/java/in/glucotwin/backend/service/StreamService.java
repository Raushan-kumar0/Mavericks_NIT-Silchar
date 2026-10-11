package in.glucotwin.backend.service;

import org.springframework.stereotype.Service;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;

/** Server-Sent Events: pushes clock ticks and new alerts to every open dashboard. */
@Service
public class StreamService {

    private final List<SseEmitter> emitters = new CopyOnWriteArrayList<>();

    public SseEmitter subscribe() {
        SseEmitter e = new SseEmitter(0L); // no timeout
        emitters.add(e);
        e.onCompletion(() -> emitters.remove(e));
        e.onTimeout(() -> emitters.remove(e));
        e.onError(t -> emitters.remove(e));
        return e;
    }

    public void broadcast(String name, Object data) {
        for (SseEmitter e : emitters) {
            try {
                e.send(SseEmitter.event().name(name).data(data));
            } catch (IOException | IllegalStateException ex) {
                emitters.remove(e);
            }
        }
    }
}
