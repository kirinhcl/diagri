"""Two users and an administrator over a workflow with greenhouse locks and access rules."""

from growbridge.config import Greenhouse
from growbridge.ports import Actor
from growbridge.sim.fixtures import DEVICE, make_protocol
from growbridge.workflow.access import Access
from growbridge.workflow.locks import GreenhouseLocks

REGISTRY = (
    Greenhouse(id="gh-01", name="One", device_id=DEVICE),
    Greenhouse(id="gh-02", name="Two", device_id="AC5-2"),
)


class People:
    """``alice`` owns the world's project and locks gh-01; ``bob`` is another user."""

    def __init__(self, world):
        self.world = world
        self.locks = GreenhouseLocks(
            world.db, world.clock, REGISTRY, world.svc.store, world.control
        )
        self.access = Access(world.svc.store, self.locks, DEVICE)
        world.svc.access = self.access

    def actor(self, name: str, role: str = "user") -> Actor:
        return Actor(kind="operator", id=name, role=role, reauth_at=self.world.clock.now())

    @property
    def alice(self) -> Actor:
        return self.actor("alice")

    @property
    def bob(self) -> Actor:
        return self.actor("bob")

    @property
    def root(self) -> Actor:
        return self.actor("root", "admin")

    def design(self, owner: Actor | None = None, protocol_id: str = "protocol-1") -> str:
        """A project of ``owner`` (alice) with one round; returns the round id."""
        world, owner = self.world, owner or self.alice
        world.project_id = world.svc.create_project(f"{owner.id}'s", owner)
        protocol = make_protocol(project_id=world.project_id, id=protocol_id)
        world.svc.save_protocol(protocol, owner)
        world.round_id = world.svc.create_round(world.project_id, protocol.id, owner)
        return world.round_id

    def pending(self, stage_id: str = "stage-1", owner: Actor | None = None) -> str:
        world, owner = self.world, owner or self.alice
        if not self.locks.held_by(owner.id):
            self.locks.lock(owner.id, ["gh-01"])
        if not world.round_id:
            self.design(owner)
        world.svc.submit_run_sheet(world.round_id, world.sheet(stage_id), owner)
        return stage_id

    async def running(self, stage_id: str = "stage-1") -> str:
        self.pending(stage_id)
        self.world.svc.approve(stage_id, self.alice)
        await self.world.svc.start_stage(stage_id, self.alice)
        return stage_id
