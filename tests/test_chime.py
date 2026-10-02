import asyncio
from pathlib import Path

from app.chime import Chimer
from app.clip import ClipError
from app.config import Config
from app.players import Player, PlayerRegistry

SOUNDS = Path(__file__).resolve().parent.parent / "sounds"
URL = "http://docker-host:5005/sounds/gong.wav"

KITCHEN = Player("Küche", "kueche.local", "RINCON_K")
LIVING = Player("Wohnzimmer", "wohnzimmer.local", "RINCON_W")
BATH = Player("Bad", "bad.local", "RINCON_B")


class FakeClient:
    instances: list["FakeClient"] = []
    failing: set[str] = set()

    def __init__(self, session, ip, player_id):
        self.ip = ip
        self.player_id = player_id
        self.played = []
        self.connects = 0
        self.connected = False
        FakeClient.instances.append(self)

    async def connect(self):
        self.connects += 1
        self.connected = True

    async def close(self):
        self.connected = False

    async def play(self, url, volume):
        if self.player_id in FakeClient.failing:
            raise ClipError("offline")
        self.played.append((url, volume))


def make_chimer(players, **overrides):
    FakeClient.instances = []
    FakeClient.failing = set()
    settings = dict(advertise_host="docker-host", sounds_dir=SOUNDS, default_volume=30, cooldown_s=0)
    settings.update(overrides)
    registry = PlayerRegistry()
    registry.set_players(players)
    return Chimer(Config(**settings), registry, client_factory=FakeClient)


def played(chimer):
    return {c.player_id: c.played for c in FakeClient.instances if c.played}


def run(coro):
    return asyncio.run(coro)


def test_plays_clip_on_each_selected_player_with_zone_volume():
    chimer = make_chimer([KITCHEN, LIVING, BATH], zone_volumes={"küche": 45})

    result = run(chimer.ring(["Küche", "wohnzimmer"], wait=True))

    assert result.status == "started"
    assert result.zones == ["Küche", "Wohnzimmer"]
    assert played(chimer) == {"RINCON_K": [(URL, 45)], "RINCON_W": [(URL, 30)]}


def test_default_zones_and_all():
    chimer = make_chimer([KITCHEN, LIVING, BATH], default_zones=["Bad"])
    run(chimer.ring(wait=True))
    assert list(played(chimer)) == ["RINCON_B"]

    chimer = make_chimer([KITCHEN, LIVING, BATH])
    run(chimer.ring(["all"], wait=True))
    assert len(played(chimer)) == 3


def test_volume_parameter_overrides_config():
    chimer = make_chimer([KITCHEN], zone_volumes={"Küche": 50})

    run(chimer.ring(["Küche"], volume=70, wait=True))

    assert played(chimer) == {"RINCON_K": [(URL, 70)]}


def test_failure_on_one_player_does_not_affect_others():
    chimer = make_chimer([KITCHEN, BATH])
    FakeClient.failing = {"RINCON_B"}

    result = run(chimer.ring(["all"], wait=True))

    assert result.status == "started"
    assert played(chimer) == {"RINCON_K": [(URL, 30)]}


def test_cooldown_ignores_repeated_rings():
    chimer = make_chimer([KITCHEN], cooldown_s=60)

    async def twice():
        first = await chimer.ring(["Küche"], wait=True)
        second = await chimer.ring(["Küche"], wait=True)
        return first, second

    first, second = run(twice())

    assert (first.status, second.status) == ("started", "ignored")
    assert played(chimer) == {"RINCON_K": [(URL, 30)]}


def test_unknown_sound_and_zone_are_errors():
    chimer = make_chimer([KITCHEN])

    assert run(chimer.ring(["Küche"], sound="../etc/passwd")).status == "error"
    assert run(chimer.ring(["Küche"], sound="fehlt")).status == "error"
    result = run(chimer.ring(["Garage"]))
    assert result.status == "error" and result.missing == ["Garage"]


def test_unknown_zones_are_reported_but_known_ones_play():
    chimer = make_chimer([KITCHEN])

    result = run(chimer.ring(["Küche", "Garage"], wait=True))

    assert result.status == "started"
    assert result.missing == ["Garage"]
    assert played(chimer) == {"RINCON_K": [(URL, 30)]}


def test_ring_returns_before_clip_is_sent():
    chimer = make_chimer([KITCHEN])

    async def ring_and_check():
        result = await chimer.ring(["Küche"])
        before = played(chimer)
        await asyncio.gather(*chimer._tasks)
        return result, before, played(chimer)

    result, before, after = run(ring_and_check())

    assert result.status == "started"
    assert before == {}
    assert after == {"RINCON_K": [(URL, 30)]}


def test_warm_up_connects_and_clients_are_reused():
    chimer = make_chimer([KITCHEN, LIVING])

    async def scenario():
        await chimer.warm_up()
        await chimer.ring(["Küche"], wait=True)

    run(scenario())

    assert len(FakeClient.instances) == 2
    assert all(c.connects == 1 for c in FakeClient.instances)
    assert chimer.is_connected(KITCHEN)


def test_client_is_recreated_when_ip_changes():
    chimer = make_chimer([KITCHEN])
    run(chimer.ring(["Küche"], wait=True))
    chimer._registry.set_players([Player("Küche", "kueche-neu.local", "RINCON_K")])

    run(chimer.ring(["Küche"], wait=True))

    assert [c.ip for c in FakeClient.instances] == ["kueche.local", "kueche-neu.local"]
