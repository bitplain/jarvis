from pathlib import Path

from scripts.smoke_railway_readiness import (
    detect_local_container_runtime,
    run_readiness,
)


def test_local_container_detection_warns_without_docker_socket() -> None:
    statuses = detect_local_container_runtime(
        docker_socket=Path("/tmp/jarvis-missing-docker.sock"),
        container_path="/usr/local/bin/container",
    )

    assert statuses["local_docker_socket"].startswith("WARN")
    assert statuses["local_apple_container_cli"].startswith("OK")


def test_railway_readiness_does_not_fail_when_only_docker_socket_is_missing() -> None:
    result = run_readiness(
        local_container_statuses={
            "local_docker_socket": "WARN Docker Desktop socket missing",
            "local_apple_container_cli": "OK Apple Container CLI available",
        }
    )

    assert result.verdict == "PASS_RAILWAY_READINESS"
