import json

from unified_semantic_archiver.media import UscMediaService


def test_settings_roundtrip_and_merge(tmp_path):
    cfg = tmp_path / "media_config.yaml"
    cfg.write_text(
        """
store:
  loss_coefficient: 0.0
stream_cache:
  enabled: false
  budget_gb: 3.0
""".strip(),
        encoding="utf-8",
    )
    settings = tmp_path / "settings.json"
    service = UscMediaService(
        storage_root=tmp_path / "storage",
        config_path=cfg,
        settings_path=settings,
    )
    service.update_settings({"stream_cache": {"enabled": True}, "store": {"loss_coefficient": 0.05}})
    current = service.get_settings()
    assert current["stream_cache"]["enabled"] is True
    assert current["stream_cache"]["budget_gb"] == 3.0
    assert current["store"]["loss_coefficient"] == 0.05

    payload = json.loads(settings.read_text(encoding="utf-8"))
    assert payload["stream_cache"]["enabled"] is True
    assert payload["store"]["loss_coefficient"] == 0.05


def test_list_jobs_scoped_by_tenant(tmp_path):
    service = UscMediaService(storage_root=tmp_path / "storage")
    a = tmp_path / "storage" / "tenant-a" / "job-a"
    b = tmp_path / "storage" / "tenant-b" / "job-b"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    (a / "input.mp4").write_bytes(b"a")
    (a / "manifest.json").write_text("{}", encoding="utf-8")
    (b / "input.mp4").write_bytes(b"b")

    jobs_a = service.list_jobs("tenant-a")
    jobs_b = service.list_jobs("tenant-b")
    assert jobs_a == [{"id": "job-a", "status": "ready"}]
    assert jobs_b == [{"id": "job-b", "status": "incomplete"}]


def test_visual_backend_default_and_experiment_settings(tmp_path):
    service = UscMediaService(storage_root=tmp_path / "storage")
    settings = service.get_settings()
    assert settings["script"]["visual_backend"] == "blip"
    assert settings["script"]["video_style_description"] == ""
    assert settings["minimization"]["experiments"]["cohort_key"] == "hash"
    assert "planar_hyperplane_v2" in settings["minimization"]["experiments"]["cohorts"]


def test_video_style_description_roundtrip(tmp_path):
    service = UscMediaService(
        storage_root=tmp_path / "storage",
        settings_path=tmp_path / "settings.json",
    )
    service.update_settings({"script": {"video_style_description": "baroque cockpit panorama"}})
    settings = service.get_settings()
    assert settings["script"]["video_style_description"] == "baroque cockpit panorama"
