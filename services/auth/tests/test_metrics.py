import pytest
from flask import Flask, jsonify

from app.metrics import BUCKETS, Metrics, escape, init_metrics


@pytest.fixture
def client():
    app = Flask(__name__)
    init_metrics(app, "demo")

    @app.get("/items/<int:item_id>")
    def item(item_id):
        return jsonify(id=item_id)

    @app.post("/items")
    def create():
        return jsonify(ok=True), 201

    return app.test_client()


def metrics_text(client):
    return client.get("/metrics").get_data(as_text=True)


def test_metrics_endpoint_is_plain_text(client):
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("text/plain")
    assert "# TYPE http_requests_total counter" in response.get_data(as_text=True)


def test_requests_are_counted_by_route_and_status(client):
    client.get("/items/1")
    client.get("/items/2")
    client.post("/items")
    text = metrics_text(client)
    assert 'http_requests_total{service="demo",method="GET",route="/items/<int:item_id>",' \
           'status="200"} 2' in text
    assert 'http_requests_total{service="demo",method="POST",route="/items",' \
           'status="201"} 1' in text


def test_unknown_paths_share_one_label(client):
    client.get("/nope")
    client.get("/other")
    text = metrics_text(client)
    assert 'route="unmatched",status="404"} 2' in text


def test_metrics_endpoint_does_not_count_itself(client):
    client.get("/metrics")
    client.get("/metrics")
    assert 'route="/metrics"' not in metrics_text(client)


def test_duration_histogram_is_cumulative(client):
    client.get("/items/1")
    text = metrics_text(client)
    count_line = [line for line in text.splitlines()
                  if line.startswith("http_request_duration_seconds_count")][0]
    assert count_line.endswith(" 1")
    buckets = [int(line.rsplit(" ", 1)[1]) for line in text.splitlines()
               if line.startswith("http_request_duration_seconds_bucket")
               and 'route="/items/<int:item_id>"' in line]
    assert len(buckets) == len(BUCKETS) + 1
    assert buckets == sorted(buckets)
    assert buckets[-1] == 1


def test_observe_puts_value_into_matching_buckets():
    metrics = Metrics("demo", clock=lambda: 100.0)
    metrics.observe("GET", "/x", 200, 0.03)
    metrics.observe("GET", "/x", 200, 3.0)
    text = metrics.render()
    assert 'le="0.05"} 1' in text
    assert 'le="2.5"} 1' in text
    assert 'le="5.0"} 2' in text
    assert 'le="+Inf"} 2' in text
    assert "http_request_duration_seconds_sum{" in text
    assert 'process_start_time_seconds{service="demo"} 100.000' in text


def test_label_values_are_escaped():
    assert escape('a"b\\c\nd') == 'a\\"b\\\\c\\nd'
