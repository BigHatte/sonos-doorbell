"""Environment seed tests."""

import os
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app.main import create_app


class TestEnvironmentSeed:
    """Seeding from environment variables on first start."""

    def test_seed_from_env_creates_boxes_and_profile(self, tmp_path, tmp_sounds_dir):
        """PLAYERS env var should create boxes."""
        os.environ["PLAYERS"] = "Box1=192.0.2.1,Box2=192.0.2.2"
        os.environ["DEFAULT_SOUND"] = "ding-dong"
        os.environ["DEFAULT_VOLUME"] = "50"

        try:
            app = create_app(
                data_dir=tmp_path,
                sounds_dir=tmp_sounds_dir,
                probe=lambda ip: {
                    "uid": f"RINCON_{ip.split('.')[-1]}_",
                    "name": f"Speaker-{ip.split('.')[-1]}",
                },
                seed_env=True,
            )

            # Use TestClient context manager to trigger lifespan
            with TestClient(app) as client:
                # Check the store directly (don't need auth for store)
                boxes = app.state.store.state.boxes
                assert len(boxes) == 2
                names = {b.name for b in boxes}
                assert "Box1" in names
                assert "Box2" in names

                # Check profile was created
                profiles = app.state.store.state.profiles
                assert len(profiles) == 1
                assert profiles[0].id == "standard"
                assert profiles[0].name == "Standard"
                assert len(profiles[0].members) == 2
        finally:
            os.environ.pop("PLAYERS", None)
            os.environ.pop("DEFAULT_SOUND", None)
            os.environ.pop("DEFAULT_VOLUME", None)

    def test_seed_default_zones_all(self, tmp_path, tmp_sounds_dir):
        """DEFAULT_ZONES=all should include all boxes."""
        os.environ["PLAYERS"] = "Box1=192.0.2.1,Box2=192.0.2.2"
        os.environ["DEFAULT_ZONES"] = "all"
        os.environ["DEFAULT_SOUND"] = "ding-dong"

        try:
            app = create_app(
                data_dir=tmp_path,
                sounds_dir=tmp_sounds_dir,
                probe=lambda ip: {
                    "uid": f"RINCON_{ip.split('.')[-1]}_",
                    "name": f"Speaker-{ip.split('.')[-1]}",
                },
                seed_env=True,
            )
            profiles = app.state.store.state.profiles
            if profiles:
                assert len(profiles[0].members) == 2
        finally:
            os.environ.pop("PLAYERS", None)
            os.environ.pop("DEFAULT_ZONES", None)
            os.environ.pop("DEFAULT_SOUND", None)

    def test_seed_default_zones_specific(self, tmp_path, tmp_sounds_dir):
        """DEFAULT_ZONES should filter boxes."""
        os.environ["PLAYERS"] = "Kitchen=192.0.2.1,Bathroom=192.0.2.2,Living=192.0.2.3"
        os.environ["DEFAULT_ZONES"] = "Kitchen,Living"
        os.environ["DEFAULT_SOUND"] = "ding-dong"

        try:
            app = create_app(
                data_dir=tmp_path,
                sounds_dir=tmp_sounds_dir,
                probe=lambda ip: {
                    "uid": f"RINCON_{ip.split('.')[-1]}_",
                    "name": f"Speaker-{ip.split('.')[-1]}",
                },
                seed_env=True,
            )
            profiles = app.state.store.state.profiles
            if profiles:
                assert len(profiles[0].members) == 2
                # Check that only Kitchen and Living are in profile
                boxes = {app.state.store.box(m.box).name for m in profiles[0].members}
                assert "Kitchen" in boxes
                assert "Living" in boxes
                assert "Bathroom" not in boxes
        finally:
            os.environ.pop("PLAYERS", None)
            os.environ.pop("DEFAULT_ZONES", None)
            os.environ.pop("DEFAULT_SOUND", None)

    def test_seed_zone_volumes(self, tmp_path, tmp_sounds_dir):
        """ZONE_VOLUMES should set per-zone volume."""
        os.environ["PLAYERS"] = "Kitchen=192.0.2.1,Bathroom=192.0.2.2"
        os.environ["ZONE_VOLUMES"] = "Kitchen=75,Bathroom=25"
        os.environ["DEFAULT_SOUND"] = "ding-dong"

        try:
            app = create_app(
                data_dir=tmp_path,
                sounds_dir=tmp_sounds_dir,
                probe=lambda ip: {
                    "uid": f"RINCON_{ip.split('.')[-1]}_",
                    "name": f"Speaker-{ip.split('.')[-1]}",
                },
                seed_env=True,
            )
            profiles = app.state.store.state.profiles
            if profiles:
                members_by_name = {}
                for member in profiles[0].members:
                    box = app.state.store.box(member.box)
                    members_by_name[box.name] = member
                assert members_by_name["Kitchen"].volume == 75
                assert members_by_name["Bathroom"].volume == 25
        finally:
            os.environ.pop("PLAYERS", None)
            os.environ.pop("ZONE_VOLUMES", None)
            os.environ.pop("DEFAULT_SOUND", None)

    def test_seed_default_volume(self, tmp_path, tmp_sounds_dir):
        """DEFAULT_VOLUME should be used for zones without specific volume."""
        os.environ["PLAYERS"] = "Box1=192.0.2.1,Box2=192.0.2.2"
        os.environ["DEFAULT_VOLUME"] = "40"
        os.environ["DEFAULT_SOUND"] = "ding-dong"

        try:
            app = create_app(
                data_dir=tmp_path,
                sounds_dir=tmp_sounds_dir,
                probe=lambda ip: {
                    "uid": f"RINCON_{ip.split('.')[-1]}_",
                    "name": f"Speaker-{ip.split('.')[-1]}",
                },
                seed_env=True,
            )
            profiles = app.state.store.state.profiles
            if profiles:
                for member in profiles[0].members:
                    assert member.volume == 40
        finally:
            os.environ.pop("PLAYERS", None)
            os.environ.pop("DEFAULT_VOLUME", None)
            os.environ.pop("DEFAULT_SOUND", None)

    def test_seed_default_sound_fallback(self, tmp_path, tmp_sounds_dir):
        """Unknown DEFAULT_SOUND should fall back to ding-dong."""
        os.environ["PLAYERS"] = "Box=192.0.2.1"
        os.environ["DEFAULT_SOUND"] = "nonexistent"

        try:
            app = create_app(
                data_dir=tmp_path,
                sounds_dir=tmp_sounds_dir,
                probe=lambda ip: {"uid": "RINCON_1_", "name": "Box"},
                seed_env=True,
            )
            profiles = app.state.store.state.profiles
            if profiles:
                assert profiles[0].sound == "ding-dong"
        finally:
            os.environ.pop("PLAYERS", None)
            os.environ.pop("DEFAULT_SOUND", None)

    def test_seed_advertise_host(self, tmp_path, tmp_sounds_dir):
        """ADVERTISE_HOST should be saved in state."""
        os.environ["ADVERTISE_HOST"] = "example.local"
        os.environ["PLAYERS"] = "Box=192.0.2.1"
        os.environ["DEFAULT_SOUND"] = "ding-dong"

        try:
            app = create_app(
                data_dir=tmp_path,
                sounds_dir=tmp_sounds_dir,
                probe=lambda ip: {"uid": "RINCON_1_", "name": "Box"},
                seed_env=True,
            )
            with TestClient(app) as client:
                assert app.state.store.state.advertise_host == "example.local"
        finally:
            os.environ.pop("ADVERTISE_HOST", None)
            os.environ.pop("PLAYERS", None)
            os.environ.pop("DEFAULT_SOUND", None)

    def test_no_seed_if_config_exists(self, tmp_path, tmp_sounds_dir):
        """Seed should not run if config.json already exists."""
        # Create initial config
        app1 = create_app(
            data_dir=tmp_path,
            sounds_dir=tmp_sounds_dir,
            seed_env=False,
        )

        # Add a box to the store
        box = app1.state.store.state.boxes
        initial_count = len(box)

        os.environ["PLAYERS"] = "NewBox=192.0.2.1"

        try:
            # Create new app - should not seed
            app2 = create_app(
                data_dir=tmp_path,
                sounds_dir=tmp_sounds_dir,
                probe=lambda ip: {"uid": "RINCON_1_", "name": "NewBox"},
                seed_env=True,
            )
            # Should have same number of boxes (no seed)
            assert len(app2.state.store.state.boxes) == initial_count
        finally:
            os.environ.pop("PLAYERS", None)

    def test_seed_only_if_seed_env_true(self, tmp_path, tmp_sounds_dir):
        """Seed should only run if seed_env=True."""
        os.environ["PLAYERS"] = "Box=192.0.2.1"

        try:
            app = create_app(
                data_dir=tmp_path,
                sounds_dir=tmp_sounds_dir,
                probe=lambda ip: {"uid": "RINCON_1_", "name": "Box"},
                seed_env=False,  # Explicitly disable seeding
            )
            assert len(app.state.store.state.boxes) == 0
        finally:
            os.environ.pop("PLAYERS", None)

    def test_seed_creates_standard_profile(self, tmp_path, tmp_sounds_dir):
        """Seed should create 'standard' profile if boxes exist."""
        os.environ["PLAYERS"] = "Box=192.0.2.1"
        os.environ["DEFAULT_SOUND"] = "ding-dong"

        try:
            app = create_app(
                data_dir=tmp_path,
                sounds_dir=tmp_sounds_dir,
                probe=lambda ip: {"uid": "RINCON_1_", "name": "Box"},
                seed_env=True,
            )
            with TestClient(app) as client:
                profiles = app.state.store.state.profiles
                standard = next((p for p in profiles if p.id == "standard"), None)
                assert standard is not None
                assert standard.name == "Standard"
        finally:
            os.environ.pop("PLAYERS", None)
            os.environ.pop("DEFAULT_SOUND", None)

    def test_seed_no_profile_if_no_boxes(self, tmp_path, tmp_sounds_dir):
        """Seed should not create profile if no boxes."""
        os.environ.pop("PLAYERS", None)  # No players

        try:
            app = create_app(
                data_dir=tmp_path,
                sounds_dir=tmp_sounds_dir,
                seed_env=True,
            )
            assert len(app.state.store.state.profiles) == 0
        finally:
            pass

    def test_seed_box_without_uid(self, tmp_path, tmp_sounds_dir):
        """Seed should handle boxes that fail to probe."""

        def probe_with_failure(ip):
            if ip == "192.0.2.2":
                raise RuntimeError("Unreachable")
            return {"uid": "RINCON_1_", "name": "Box1"}

        os.environ["PLAYERS"] = "Box1=192.0.2.1,Box2=192.0.2.2"
        os.environ["DEFAULT_SOUND"] = "ding-dong"

        try:
            app = create_app(
                data_dir=tmp_path,
                sounds_dir=tmp_sounds_dir,
                probe=probe_with_failure,
                seed_env=True,
            )
            with TestClient(app) as client:
                boxes = app.state.store.state.boxes
                assert len(boxes) == 2
                # Box2 should have uid=None
                box2 = next(b for b in boxes if b.name == "Box2")
                assert box2.uid is None
        finally:
            os.environ.pop("PLAYERS", None)
            os.environ.pop("DEFAULT_SOUND", None)
