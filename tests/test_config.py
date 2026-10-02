from app.config import load_config


def test_settings_from_environment_without_file(tmp_path, monkeypatch):
    monkeypatch.setenv("ADVERTISE_HOST", "docker-host")
    monkeypatch.setenv("DEFAULT_ZONES", "Wohnzimmer, Küche")
    monkeypatch.setenv("ZONE_VOLUMES", "Küche=40, Bad = 20")
    monkeypatch.setenv("PLAYERS", "Küche=kueche.local,Bad=bad.local")
    monkeypatch.setenv("DEFAULT_VOLUME", "25")
    monkeypatch.setenv("COOLDOWN_S", "5")

    config = load_config(tmp_path / "missing.yaml")

    assert config.advertise_host == "docker-host"
    assert config.default_zones == ["Wohnzimmer", "Küche"]
    assert config.zone_volumes == {"Küche": 40, "Bad": 20}
    assert config.players == {"Küche": "kueche.local", "Bad": "bad.local"}
    assert config.default_volume == 25
    assert config.cooldown_s == 5.0
    assert config.port == 5005


def test_empty_environment_values_fall_back_to_file(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text(
        "advertise_host: file-host\nplayers:\n  Küche: kueche.file\nzone_volumes:\n  Küche: 45\n",
        encoding="utf-8",
    )
    for key in ("ADVERTISE_HOST", "PLAYERS", "ZONE_VOLUMES", "DEFAULT_ZONES"):
        monkeypatch.setenv(key, "")

    config = load_config(path)

    assert config.advertise_host == "file-host"
    assert config.players == {"Küche": "kueche.file"}
    assert config.zone_volumes == {"Küche": 45}
    assert config.default_zones == ["all"]


def test_missing_advertise_host_is_reported(tmp_path, monkeypatch):
    monkeypatch.delenv("ADVERTISE_HOST", raising=False)
    try:
        load_config(tmp_path / "missing.yaml")
    except ValueError as error:
        assert "ADVERTISE_HOST" in str(error)
    else:
        raise AssertionError("expected ValueError")
