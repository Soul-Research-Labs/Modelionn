"""Base neuron with Modelionn-specific config and lifecycle."""

from __future__ import annotations

import argparse
import logging
from abc import ABC, abstractmethod

import bittensor as bt

from registry.core.config import settings

logger = logging.getLogger(__name__)


class BaseNeuron(ABC):
    """Shared foundation for both miner and validator neurons."""

    neuron_type: str = "base"

    def __init__(self, config: bt.config | None = None) -> None:
        self.config = config or self._build_config()
        bt.logging(config=self.config)

        # Core Bittensor objects
        self.wallet = bt.wallet(config=self.config)
        self.subtensor = bt.subtensor(config=self.config)
        self.metagraph = self.subtensor.metagraph(netuid=self.config.netuid)

        # Check registration
        self.uid = self._get_uid()
        logger.info(
            "%s neuron uid=%d  hotkey=%s  network=%s  netuid=%d",
            self.neuron_type,
            self.uid,
            self.wallet.hotkey.ss58_address,
            self.config.subtensor.network,
            self.config.netuid,
        )

    # ── Config ───────────────────────────────────────────────

    @classmethod
    def _build_config(cls) -> bt.config:
        parser = argparse.ArgumentParser()
        bt.wallet.add_args(parser)
        bt.subtensor.add_args(parser)
        bt.logging.add_args(parser)
        bt.axon.add_args(parser)

        parser.add_argument("--netuid", type=int, default=settings.bt_netuid)
        parser.add_argument("--neuron.epoch_length", type=int, default=100)
        parser.add_argument("--neuron.sample_size", type=int, default=50)
        parser.add_argument("--neuron.timeout", type=float, default=30.0)
        parser.add_argument("--neuron.moving_average_alpha", type=float, default=0.1)

        return bt.config(parser)

    def _get_uid(self) -> int:
        hotkey = self.wallet.hotkey.ss58_address
        if hotkey not in self.metagraph.hotkeys:
            raise RuntimeError(
                f"Hotkey {hotkey} is not registered on netuid {self.config.netuid}. "
                "Run: btcli subnet register"
            )
        return self.metagraph.hotkeys.index(hotkey)

    # ── Lifecycle ────────────────────────────────────────────

    def sync(self) -> None:
        """Re-sync the metagraph from chain."""
        self.metagraph.sync(subtensor=self.subtensor)
        self.uid = self._get_uid()

    @abstractmethod
    async def forward(self) -> None:
        """Main loop iteration — implemented by miner / validator."""

    @abstractmethod
    def run(self) -> None:
        """Start the neuron main loop."""
