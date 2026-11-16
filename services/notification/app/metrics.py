import threading
import time

from flask import Response, g, request

BUCKETS = (0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)
CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def escape(value):
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def labels(**pairs):
    return ",".join(f'{name}="{escape(value)}"' for name, value in pairs.items())


class Metrics:
    def __init__(self, service, clock=time.time):
        self.service = service
        self.started = clock()
        self.lock = threading.Lock()
        self.requests = {}
        self.durations = {}

    def observe(self, method, route, status, seconds):
        with self.lock:
            key = (method, route, str(status))
            self.requests[key] = self.requests.get(key, 0) + 1
            hist = self.durations.setdefault(
                (method, route), {"buckets": [0] * len(BUCKETS), "sum": 0.0, "count": 0})
            for index, bound in enumerate(BUCKETS):
                if seconds <= bound:
                    hist["buckets"][index] += 1
            hist["sum"] += seconds
            hist["count"] += 1

    def render(self):
        service = self.service
        lines = [
            "# HELP http_requests_total Number of HTTP requests handled by the service.",
            "# TYPE http_requests_total counter",
        ]
        with self.lock:
            for (method, route, status), count in sorted(self.requests.items()):
                lines.append("http_requests_total{%s} %d" % (
                    labels(service=service, method=method, route=route, status=status), count))
            lines += [
                "# HELP http_request_duration_seconds Time spent handling HTTP requests.",
                "# TYPE http_request_duration_seconds histogram",
            ]
            for (method, route), hist in sorted(self.durations.items()):
                base = dict(service=service, method=method, route=route)
                for bound, value in zip(BUCKETS, hist["buckets"]):
                    lines.append("http_request_duration_seconds_bucket{%s} %d" % (
                        labels(**base, le=bound), value))
                lines.append("http_request_duration_seconds_bucket{%s} %d" % (
                    labels(**base, le="+Inf"), hist["count"]))
                lines.append("http_request_duration_seconds_sum{%s} %.6f" % (
                    labels(**base), hist["sum"]))
                lines.append("http_request_duration_seconds_count{%s} %d" % (
                    labels(**base), hist["count"]))
        lines += [
            "# HELP process_start_time_seconds Start time of the service in unix seconds.",
            "# TYPE process_start_time_seconds gauge",
            "process_start_time_seconds{%s} %.3f" % (labels(service=service), self.started),
        ]
        return "\n".join(lines) + "\n"


def init_metrics(app, service):
    metrics = Metrics(service)

    @app.before_request
    def start_timer():
        g.metrics_started = time.perf_counter()

    @app.after_request
    def record(response):
        if request.path != "/metrics":
            started = g.get("metrics_started")
            elapsed = time.perf_counter() - started if started is not None else 0.0
            route = request.url_rule.rule if request.url_rule else "unmatched"
            metrics.observe(request.method, route, response.status_code, elapsed)
        return response

    @app.get("/metrics")
    def metrics_view():
        return Response(metrics.render(), mimetype="text/plain",
                        headers={"Content-Type": CONTENT_TYPE})

    return metrics
