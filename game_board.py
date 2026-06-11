"""
Basic Land Game — State Management
Based on rules from:
https://ultimateguard.com/en/blog/basic-land-game-rules-gameplay-strategy-magic-the-gathering-skura

Each player starts with a library of 50 cards (10 each of Forest, Island,
Mountain, Plains, Swamp), draws 5 to hand, and takes turns playing one land
per turn. Win by assembling either one of each land type (Domain) or 5 copies
of the same land type (Mono) in your active zone.

Land effects:
  Island  — draw a card; OR discard Island + another land to counter an
            opponent's land play (and its effect), sending that land to
            the opponent's graveyard instead.
  Mountain — destroy one of the opponent's active lands (target declared
             before the opponent can respond with a counter).
  Forest   — return a land from your graveyard to your hand.
  Swamp    — look at the opponent's hand and choose a card for them to
             discard (target chosen at resolution, so Island-counter must
             be committed before the discard target is known).
  Plains   — copy the effect of one of your other non-Plains active lands
             (target declared before the opponent can respond).

Counter window (Island):
  After a land play is announced (including its declared targets where
  applicable), the non-active player may spend one Island + one other land
  from hand to counter that play. The played land is instead discarded and
  its effect does not occur. No effect if the active player plays an Island
  (countering a draw is legal but not very useful).
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class LandType(str, Enum):
    FOREST  = "forest"
    ISLAND  = "island"
    MOUNTAIN = "mountain"
    PLAINS  = "plains"
    SWAMP   = "swamp"


class GamePhase(Enum):
    """Coarse phases within a single turn."""
    DRAW                   = auto()   # Active player may draw (skipped on very first turn)
    PLAY_OR_PASS           = auto()   # Active player decides: play a land or pass
    AWAIT_COUNTER          = auto()   # Opponent decides whether to counter the land play
    AWAIT_COUNTER_COUNTER  = auto()   # Active player whether to counter the counter
    RESOLVE_EFFECT         = auto()   # Effect resolves (needs additional targeting info)
    GAME_OVER              = auto()


class ActionType(Enum):
    # Active-player actions
    PLAY_LAND          = auto()   # Play a land from hand; requires card_id
    PASS_TURN          = auto()   # Skip land play and pass the turn

    # Opponent (counter) actions — only valid during AWAIT_COUNTER phase
    COUNTER_LAND       = auto()   # Spend Island + another land to counter
    ALLOW_LAND         = auto()   # Let the land resolve

    SPECIFY_TARGET     = auto()   # Choose which card to target for a land's effect

    FORFEIT            = auto()   # Surrender the game


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Card:
    """A single land card with a unique runtime ID."""
    land_type: LandType
    card_id:   str = field(default_factory=lambda: str(uuid.uuid4()))

    def __str__(self) -> str:
        return f"Card({self.land_type.value}, id={self.card_id[:8]})"

    def __repr__(self) -> str:
        return str(self)

    def to_dict(self) -> dict:
        return {"card_id": self.card_id, "land_type": self.land_type.value}

@dataclass
class PlayerState:
    player_id: int                            # 0 or 1
    library:   list[Card] = field(default_factory=list)
    hand:      list[Card] = field(default_factory=list)
    active:    list[Card] = field(default_factory=list)
    graveyard: list[Card] = field(default_factory=list)

    # Which hand cards are currently visible to the opponent
    revealed_card_ids: set[str] = field(default_factory=set)

    def hand_card(self, card_id: str) -> Optional[Card]:
        return next((c for c in self.hand if c.card_id == card_id), None)

    def active_card(self, card_id: str) -> Optional[Card]:
        return next((c for c in self.active if c.card_id == card_id), None)

    def graveyard_card(self, card_id: str) -> Optional[Card]:
        return next((c for c in self.graveyard if c.card_id == card_id), None)

    def draw(self) -> Optional[Card]:
        """Draw the top card from the library into hand. Returns None if empty."""
        if not self.library:
            return None
        card = self.library.pop()
        self.hand.append(card)
        return card

    def move_hand_to_graveyard(self, card: Card) -> None:
        self.hand.remove(card)
        self.graveyard.append(card)

    def move_active_to_graveyard(self, card: Card) -> None:
        self.active.remove(card)
        self.graveyard.append(card)

    def move_graveyard_to_hand(self, card: Card) -> None:
        self.graveyard.remove(card)
        self.hand.append(card)

    def check_win(self) -> bool:
        """True if this player has achieved a win condition."""
        types_in_play = {c.land_type for c in self.active}
        # Domain: one of each basic land type
        if len(types_in_play) == 5:
            return True
        # Mono: five copies of a single land type
        from collections import Counter
        counts = Counter(c.land_type for c in self.active)
        return any(v >= 5 for v in counts.values())


@dataclass(frozen=True)
class PublicPlayerState:
    """Public (opponent-safe) snapshot of one player's state."""
    player_id:    int
    library_size: int
    hand_size:    int
    revealed_hand: list[Card]
    active:       list[Card]
    graveyard:    list[Card]

    def to_dict(self) -> dict:
        return {
            "player_id":    self.player_id,
            "library_size": self.library_size,
            "hand_size":    self.hand_size,
            "revealed_hand": [c.to_dict() for c in self.revealed_hand],
            "active":       [c.to_dict() for c in self.active],
            "graveyard":    [c.to_dict() for c in self.graveyard],
        }


@dataclass
class PublicGameState:
    """
    Serialisable snapshot of all public game information.

    Hand sizes are shown; individual hand cards are hidden unless revealed.
    Library sizes are shown; order is hidden.
    """
    phase:        GamePhase # Serialized as GamePhase.name
    active_player: int
    turn_number:  int
    winner:       Optional[int]
    pending_play: Optional[Card]  # Serialized as Card.__str__() or None
    players:      list[PublicPlayerState]

    def get_awaited_player(self) -> int:
        """Returns the index of the player who needs to take the next action."""
        if self.phase == GamePhase.AWAIT_COUNTER:
            # Non-active player decides whether to counter
            return 1 - self.active_player
        return self.active_player

    def to_dict(self) -> dict:
        return {
            "phase":         self.phase.name,
            "active_player": self.active_player,
            "turn_number":   self.turn_number,
            "winner":        self.winner,
            "pending_play":  str(self.pending_play),
            "players":       [p.to_dict() for p in self.players],
        }


# ---------------------------------------------------------------------------
# Action / Result types
# ---------------------------------------------------------------------------

@dataclass
class GameAction:
    """
    Describes an action a player wishes to take.

    Fields used vary by action_type:
      PLAY_LAND       : player_id, card_id (the land being played)
      PASS_TURN       : player_id
      COUNTER_LAND    : player_id, card_id (Island), counter_second_card_id
      ALLOW_LAND      : player_id
      SPECIFY_TARGET  : player_id, target_card_id (must be valid for the pending card effect)
    """
    action_type:           ActionType
    player_id:             int
    card_id:               Optional[str] = None  # Primary card (played or Island)
    counter_second_card_id: Optional[str] = None  # Second card for counter
    target_card_id:        Optional[str] = None  # Effect target


@dataclass
class ActionResult:
    """Result of applying a GameAction."""
    success: bool
    message: str
    events:  list[str] = field(default_factory=list)  # Log of what happened

    @staticmethod
    def ok(message: str, events: Optional[list[str]] = None) -> "ActionResult":
        return ActionResult(True, message, events or [])

    @staticmethod
    def fail(message: str) -> "ActionResult":
        return ActionResult(False, message, [])


# ---------------------------------------------------------------------------
# Main game class
# ---------------------------------------------------------------------------

class BasicLandGame:
    """
    Manages all state for a two-player Basic Land Game.

    The caller drives the game by submitting GameAction objects via
    ``apply_action()``.  The game enforces legality and returns an
    ActionResult describing what happened.

    Turn flow:
        1. DRAW          — active player draws (skipped on first turn for
                           the player going first).
        2. PLAY_OR_PASS  — active player either plays a land or passes.
           If a land is played:
        3. AWAIT_COUNTER — opponent decides to counter or allow.
        4. AWAIT_COUNTER_COUNTER — if countered, active decides to counter back.
        4. RESOLVE_EFFECT — if the land has a targeting effect (Mountain,
                            Forest, Plains, Swamp) the active player
                            provides the target via a follow-up action.
                            Island resolves immediately with no extra input.
    """

    LAND_TYPES = list(LandType)
    CARDS_PER_TYPE = 10
    OPENING_HAND_SIZE = 5

    def __init__(self, seed: Optional[int] = None) -> None:
        self.rand = random.Random(seed)

        self.players: list[PlayerState] = [
            PlayerState(player_id=0),
            PlayerState(player_id=1),
        ]

        # Determine who goes first
        self.active_player_idx: int = self.rand.randint(0, 1)
        self.turn_number: int = 1

        # Pending play info (set during AWAIT_COUNTER / RESOLVE_EFFECT)
        self._pending_card: Optional[Card] = None

        # Winner (set when the game ends)
        self.winner: Optional[int] = None

        # Event log accessible to UI
        self.event_log: list[str] = []

        # Set up libraries and draw opening hands
        self._setup_libraries()
        self._draw_opening_hands()

        # Immediately check draw phase for first player
        # (first player skips draw on turn 1)
        self._log(f"Player {self.active_player_idx} goes first and skips their first draw.")
        self.phase = GamePhase.PLAY_OR_PASS

    def get_inactive_player_idx(self)-> int:
        return 1 - self.active_player_idx
    
    def get_player_idx_deciding_on_counter(self) -> int:
        # If an even number of counter spells have been played, the opponent is deciding whether to counter the played land.
        # For odd numbers, the active player is deciding whether to counter the counter.
        if self.phase == GamePhase.AWAIT_COUNTER:
            return self.get_inactive_player_idx()
        # AWAIT_COUNTER_COUNTER
        else:
            return self.active_player_idx

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def apply_action(self, action: GameAction) -> ActionResult:
        """
        Validate and apply a game action. Returns ActionResult.
        Does NOT mutate state if validation fails.
        """
        if self.phase == GamePhase.GAME_OVER:
            return ActionResult.fail("The game is already over.")

        handler = {
            ActionType.PLAY_LAND:       self._handle_play_land,
            ActionType.PASS_TURN:       self._handle_pass_turn,
            ActionType.COUNTER_LAND:    self._handle_counter_land,
            ActionType.ALLOW_LAND:      self._handle_allow_land,
            ActionType.SPECIFY_TARGET:  self._resolve_targeted_effect,
            ActionType.FORFEIT:          self._handle_forfeit,
        }.get(action.action_type)

        if handler is None:
            return ActionResult.fail(f"Unknown action type: {action.action_type}")

        return handler(action)

    # ------------------------------------------------------------------
    # Public read-only helpers
    # ------------------------------------------------------------------

    def public_state(self) -> PublicGameState:
        """
        Return a snapshot of all public information as a PublicGameState.
        Hand sizes are shown; individual hand cards are hidden unless
        revealed.  Library sizes are shown; order is hidden.

        Call ``.to_dict()`` on the result for a JSON-serialisable representation.
        """
        player_snapshots = []
        for p in self.players:
            player_snapshots.append(PublicPlayerState(
                player_id=p.player_id,
                library_size=len(p.library),
                hand_size=len(p.hand),
                revealed_hand=[c for c in p.hand if c.card_id in p.revealed_card_ids],
                active=list(p.active),
                graveyard=list(p.graveyard),
            ))
        return PublicGameState(
            phase=self.phase,
            active_player=self.active_player_idx,
            turn_number=self.turn_number,
            winner=self.winner,
            pending_play=self._pending_card,
            players=player_snapshots,
        )

    def player_hand(self, player_id: int) -> list[dict]:
        """
        Return the full hand for a given player (intended for that player's
        private view only — the UI must not expose this to the opponent).
        """
        return [
            {"card_id": c.card_id, "land_type": c.land_type.value}
            for c in self.players[player_id].hand
        ]

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    def _handle_play_land(self, action: GameAction) -> ActionResult:
        if self.phase != GamePhase.PLAY_OR_PASS:
            return ActionResult.fail(
                f"Cannot play a land during phase {self.phase.name}."
            )
        if action.player_id != self.active_player_idx:
            return ActionResult.fail("It is not your turn.")
        if action.card_id is None:
            return ActionResult.fail("card_id is required to play a land.")

        player = self.players[action.player_id]
        card = player.hand_card(action.card_id)
        if card is None:
            return ActionResult.fail(
                f"Card {action.card_id} is not in player {action.player_id}'s hand."
            )

        # Announce the play; store pending state
        self._pending_card = card
        player.hand.remove(card)
        self.phase = GamePhase.AWAIT_COUNTER

        self._log(
            f"Player {action.player_id} announces play of {card.land_type.value} "
            f"(id={card.card_id[:8]})."
        )
        return ActionResult.ok(
            f"Land play announced: {card.land_type.value}. "
            "Opponent may now counter (COUNTER_LAND) or allow (ALLOW_LAND).",
            events=list(self.event_log[-1:]),
        )

    def _handle_pass_turn(self, action: GameAction) -> ActionResult:
        if self.phase != GamePhase.PLAY_OR_PASS:
            return ActionResult.fail(
                f"Cannot pass during phase {self.phase.name}."
            )
        if action.player_id != self.active_player_idx:
            return ActionResult.fail("It is not your turn.")

        self._log(f"Player {action.player_id} passes without playing a land.")
        self._advance_turn()
        return ActionResult.ok("Turn passed.", events=list(self.event_log[-3:]))

    def _handle_counter_land(self, action: GameAction) -> ActionResult:
        if self.phase not in (GamePhase.AWAIT_COUNTER, GamePhase.AWAIT_COUNTER_COUNTER):
            return ActionResult.fail(
                f"No land play is pending to counter (phase={self.phase.name})."
            )
        expected_player_idx = self.get_player_idx_deciding_on_counter()
        if action.player_id != expected_player_idx:
            return ActionResult.fail(
                f"Waiting on player {expected_player_idx} to allow/counter a land play."
            )
        if action.card_id is None or action.counter_second_card_id is None:
            return ActionResult.fail(
                "counter requires card_id (Island) and counter_second_card_id (any other land)."
            )

        assert self._pending_card is not None

        counter_player = self.players[expected_player_idx]

        island_card = counter_player.hand_card(action.card_id)
        if island_card is None:
            return ActionResult.fail(
                f"Card {action.card_id} is not in your hand."
            )
        if island_card.land_type != LandType.ISLAND:
            return ActionResult.fail(
                "The first counter card must be an Island."
            )

        second_card = counter_player.hand_card(action.counter_second_card_id)
        if second_card is None:
            return ActionResult.fail(
                f"Card {action.counter_second_card_id} is not in your hand."
            )
        if second_card.card_id == island_card.card_id:
            return ActionResult.fail(
                "The two counter cards must be different cards."
            )

        # Pay the counter cost: discard Island + second card
        counter_player.move_hand_to_graveyard(island_card)
        counter_player.move_hand_to_graveyard(second_card)

        self.phase = GamePhase.AWAIT_COUNTER_COUNTER if self.phase == GamePhase.AWAIT_COUNTER else GamePhase.AWAIT_COUNTER

        self._log(
            f"Player {expected_player_idx} countered with Island + "
            f"{second_card.land_type.value}. "
        )

        return ActionResult.ok(
            "Counter used successfully.",
            events=list(self.event_log[-5:]),
        )

    def _handle_allow_land(self, action: GameAction) -> ActionResult:
        if self.phase not in (GamePhase.AWAIT_COUNTER, GamePhase.AWAIT_COUNTER_COUNTER):
            return ActionResult.fail(
                f"No land play is pending (phase={self.phase.name})."
            )
        expected_player_idx = self.get_player_idx_deciding_on_counter()
        if action.player_id != expected_player_idx:
            return ActionResult.fail(
                f"Waiting on player {expected_player_idx} to allow/counter a land play."
            )
        
        # AWAIT_COUNTER phase implies there's a pending card/
        assert self._pending_card is not None

        # No counter, or counter was countered
        if self.phase == GamePhase.AWAIT_COUNTER:
            self._log(
                f"Player {action.player_id} allows the land play."
            )
            return self._resolve_land()
        # Land drop was countered
        else:
            # The played land goes to the active player's graveyard
            attacker = self.players[self.active_player_idx]
            attacker.graveyard.append(self._pending_card)

            self._log(
                f"Player {self.active_player_idx}'s {self._pending_card.land_type.value} "
                f"was discarded."
            )

            self._pending_card = None
            self._advance_turn()
            return ActionResult.ok(
                "Land play countered successfully.",
                events=list(self.event_log[-5:]),
            )

    def _handle_forfeit(self, action: GameAction) -> ActionResult:
        player_idx = action.player_id
        opponent_idx = 1 - player_idx

        self.winner = opponent_idx
        self.phase = GamePhase.GAME_OVER
        self._pending_card = None
        self._log(f"Player {player_idx} has forfeited the game.")
        self._log(f"Player {opponent_idx} wins!")

        return ActionResult.ok(
            f"Player {player_idx} forfeited. Player {opponent_idx} wins!",
            events=list(self.event_log[-2:]),
        )

    # ------------------------------------------------------------------
    # Land resolution
    # ------------------------------------------------------------------

    def _resolve_land(self) -> ActionResult:
        """
        Move the pending card from hand to active, then either immediately
        apply its effect (Island) or enter RESOLVE_EFFECT for targeted ones.
        """
        assert self._pending_card is not None
        card = self._pending_card
        player_idx = self.active_player_idx
        player = self.players[player_idx]

        player.active.append(self._pending_card)
        self._log(f"Player {player_idx} plays {card.land_type.value}.")

        # Check win condition immediately after playing
        if player.check_win():
            self.winner = player_idx
            self.phase = GamePhase.GAME_OVER
            self._log(f"Player {player_idx} wins!")
            self._pending_card = None
            return ActionResult.ok(
                f"Player {player_idx} wins!",
                events=list(self.event_log[-4:]),
            )

        # Island resolves immediately (draw a card)
        if card.land_type == LandType.ISLAND:
            drawn = player.draw()
            if drawn:
                self._log(
                    f"Island effect: Player {player_idx} draws "
                    f"{drawn.land_type.value} (id={drawn.card_id[:8]})."
                )
            else:
                self._log(f"Island effect: Player {player_idx}'s library is empty.")
            self._pending_card = None
            self._advance_turn()
            return ActionResult.ok(
                "Island played; card drawn. Turn advanced.",
                events=list(self.event_log[-4:]),
            )

        # Lands with no valid targets resolve with no effect
        # (e.g. Mountain when opponent has no active lands)
        if card.land_type == LandType.MOUNTAIN:
            opponent = self.players[self.get_inactive_player_idx()]
            if not opponent.active:
                self._log(
                    "Mountain effect: opponent has no active lands to destroy."
                )
                self._pending_card = None
                self._advance_turn()
                return ActionResult.ok(
                    "Mountain played; no opponent lands to destroy. Turn advanced.",
                    events=list(self.event_log[-4:]),
                )

        if card.land_type == LandType.FOREST:
            grave_yard = self.players[self.active_player_idx].graveyard
            if not grave_yard:
                self._log("Forest effect: no lands in graveyard.")
                self._pending_card = None
                self._advance_turn()
                return ActionResult.ok(
                    "Forest played; no graveyard lands available. Turn advanced.",
                    events=list(self.event_log[-4:]),
                )

        if card.land_type == LandType.SWAMP:
            opponent = self.players[self.get_inactive_player_idx()]
            if not opponent.hand:
                self._log("Swamp effect: opponent's hand is empty.")
                # Reveal that hand is empty
                self._pending_card = None
                self._advance_turn()
                return ActionResult.ok(
                    "Swamp played; opponent hand is empty. Turn advanced.",
                    events=list(self.event_log[-4:]),
                )
            # Reveal opponent's hand to the active player
            for c in opponent.hand:
                opponent.revealed_card_ids.add(c.card_id)
            self._log(
                f"Swamp effect: Player {player_idx} sees opponent's hand — "
                f"{[c.land_type.value for c in opponent.hand]}."
            )

        if card.land_type == LandType.PLAINS:
            # Must have at least one non-Plains active land to copy
            non_plains_active = [
                c for c in player.active
                if c.land_type != LandType.PLAINS and c.card_id != card.card_id
            ]
            if not non_plains_active:
                self._log(
                    "Plains effect: no non-Plains active lands to copy an effect from."
                )
                self._pending_card = None
                self._advance_turn()
                return ActionResult.ok(
                    "Plains played; no non-Plains active lands to copy. Turn advanced.",
                    events=list(self.event_log[-4:]),
                )

        # Transition to effect-resolution phase for targeting
        self.phase = GamePhase.RESOLVE_EFFECT
        prompts = {
            LandType.MOUNTAIN: "Provide SPECIFY_TARGET: target_card_id = opponent active land to destroy.",
            LandType.FOREST:   "Provide SPECIFY_TARGET: target_card_id = graveyard land to return to hand.",
            LandType.SWAMP:    "Provide SPECIFY_TARGET: target_card_id = opponent hand card to discard.",
            LandType.PLAINS:   "Provide SPECIFY_TARGET: target_card_id = one of your own active non-Plains lands to copy.",
        }
        return ActionResult.ok(
            prompts[card.land_type],
            events=list(self.event_log[-4:]),
        )

    def _resolve_targeted_effect(
        self,
        action: GameAction
    ) -> ActionResult:
        if self.phase != GamePhase.RESOLVE_EFFECT:
            return ActionResult.fail(
                f"Not in effect-resolution phase (phase={self.phase.name})."
            )
        
        # The RESOLVE_EFFECT phase implies a pending card.
        assert self._pending_card is not None
        
        apply_fn = {
           LandType.MOUNTAIN : self._apply_mountain,
           LandType.SWAMP : self._apply_swamp,
           LandType.FOREST : self._apply_forest,
           LandType.PLAINS : self._apply_plains,
        }[self._pending_card.land_type]

        if action.player_id != self.active_player_idx:
            return ActionResult.fail("It is not your turn to resolve an effect.")
        if action.target_card_id is None:
            return ActionResult.fail("target_card_id is required.")

        result = apply_fn(action)
        # Plains handle phase transition internally
        if apply_fn != self._apply_plains and result.success:
            self._pending_card = None
            self._advance_turn()
        return result

    # ------------------------------------------------------------------
    # Individual effect applicators
    # ------------------------------------------------------------------

    def _apply_mountain(self, action: GameAction) -> ActionResult:
        player_idx = self.active_player_idx
        opponent = self.players[self.get_inactive_player_idx()]
        target = opponent.active_card(action.target_card_id)
        if target is None:
            return ActionResult.fail(
                f"Card {action.target_card_id} is not in opponent's active zone."
            )
        opponent.move_active_to_graveyard(target)
        self._log(
            f"Mountain effect: Player {player_idx} destroys opponent's "
            f"{target.land_type.value} (id={target.card_id[:8]})."
        )
        return ActionResult.ok("Mountain effect applied.", events=list(self.event_log[-2:]))

    def _apply_forest(self, action: GameAction) -> ActionResult:
        player_idx = self.active_player_idx
        player = self.players[player_idx]
        
        # Forest can only return cards from the active player's own graveyard
        card = player.graveyard_card(action.target_card_id)
        if card is None:
            return ActionResult.fail(
                f"Card {action.target_card_id} is not in your graveyard."
            )
        
        # Return the card from graveyard to hand
        player.move_graveyard_to_hand(card)
        
        # Mark the card as revealed since it was returned from the public graveyard
        player.revealed_card_ids.add(card.card_id)
        
        self._log(
            f"Forest effect: Player {player_idx} returns "
            f"{card.land_type.value} (id={card.card_id[:8]}) from graveyard to hand."
        )
        return ActionResult.ok("Forest effect applied.", events=list(self.event_log[-2:]))

    def _apply_swamp(self, action: GameAction) -> ActionResult:
        player_idx = self.active_player_idx
        opponent = self.players[self.get_inactive_player_idx()]
        target = opponent.hand_card(action.target_card_id)
        if target is None:
            return ActionResult.fail(
                f"Card {action.target_card_id} is not in opponent's hand."
            )
        opponent.move_hand_to_graveyard(target)
        self._log(
            f"Swamp effect: Player {player_idx} discards opponent's "
            f"{target.land_type.value} (id={target.card_id[:8]})."
        )
        return ActionResult.ok("Swamp effect applied.", events=list(self.event_log[-2:]))

    def _apply_plains(self, action: GameAction) -> ActionResult:
        player_idx = self.active_player_idx
        player = self.players[player_idx]
        # Find the chosen active (non-Plains) land to copy
        target = player.active_card(action.target_card_id)
        if target is None:
            return ActionResult.fail(
                f"Card {action.target_card_id} is not in your active zone."
            )
        if target.land_type == LandType.PLAINS:
            return ActionResult.fail(
                "Plains cannot copy the effect of another Plains."
            )
        # Cannot copy the Plains card just played
        if target.card_id == self._pending_card.card_id:
            return ActionResult.fail(
                "Cannot copy the Plains card itself."
            )

        self._log(
            f"Plains effect: Player {player_idx} copies {target.land_type.value} effect."
        )

        # Trigger the copied effect. Island resolves immediately.
        if target.land_type == LandType.ISLAND:
            drawn = player.draw()
            if drawn:
                self._log(
                    f"Copied Island effect: Player {player_idx} draws "
                    f"{drawn.land_type.value} (id={drawn.card_id[:8]})."
                )
            else:
                self._log(f"Copied Island: library is empty.")
            self._pending_card = None
            self._advance_turn()
            return ActionResult.ok("Plains→Island copy applied.", events=list(self.event_log[-3:]))

        # Check for empty targets just as _resolve_land does
        if target.land_type == LandType.MOUNTAIN:
            opponent = self.players[self.get_inactive_player_idx()]
            if not opponent.active:
                self._log("Copied Mountain: opponent has no active lands.")
                self._pending_card = None
                self._advance_turn()
                return ActionResult.ok(
                    "Plains→Mountain: no target. Turn advanced.",
                    events=list(self.event_log[-3:]),
                )

        if target.land_type == LandType.FOREST:
            grave_yard = self.players[self.active_player_idx].graveyard
            if not grave_yard:
                self._log("Copied Forest: no lands in graveyard.")
                self._pending_card = None
                self._advance_turn()
                return ActionResult.ok(
                    "Plains→Forest: no graveyard lands. Turn advanced.",
                    events=list(self.event_log[-3:]),
                )

        if target.land_type == LandType.SWAMP:
            opponent = self.players[self.get_inactive_player_idx()]
            if not opponent.hand:
                self._log("Copied Swamp: opponent hand is empty.")
                self._pending_card = None
                self._advance_turn()
                return ActionResult.ok(
                    "Plains→Swamp: opponent hand empty. Turn advanced.",
                    events=list(self.event_log[-3:]),
                )
            for c in opponent.hand:
                opponent.revealed_card_ids.add(c.card_id)
            self._log(
                f"Copied Swamp: Player {player_idx} sees opponent's hand — "
                f"{[c.land_type.value for c in opponent.hand]}."
            )

        # For targeted effects, re-enter RESOLVE_EFFECT with the copied land type
        # We swap the pending card's effective type by replacing _pending_card
        # with a virtual reference — we store the copied-land target type so the
        # next resolution handler knows what to do.
        self._plains_copied_land = target.land_type
        self._pending_card = target      # reuse target card so type checks pass
        self.phase = GamePhase.RESOLVE_EFFECT

        prompts = {
            LandType.MOUNTAIN: "Provide opponent active land for Plains copy.",
            LandType.FOREST:   "Provide graveyard land for Plains copy.",
            LandType.SWAMP:    "Provide opponent hand card for Plains copy.",
        }
        return ActionResult.ok(
            prompts.get(target.land_type, "Provide effect target for Plains copy."),
            events=list(self.event_log[-3:]),
        )

    # ------------------------------------------------------------------
    # Turn management
    # ------------------------------------------------------------------

    def _advance_turn(self) -> None:
        """Switch active player and advance to the next turn's DRAW phase."""
        self.active_player_idx = 1 - self.active_player_idx
        self.turn_number += 1
        self.phase = GamePhase.DRAW
        self._do_draw_phase()

    def _do_draw_phase(self) -> None:
        """Execute the draw for the active player and advance to PLAY_OR_PASS."""
        player = self.players[self.active_player_idx]
        drawn = player.draw()
        if drawn:
            self._log(
                f"Player {self.active_player_idx} draws "
                f"{drawn.land_type.value} (id={drawn.card_id[:8]})."
            )
        else:
            self._log(
                f"Player {self.active_player_idx}'s library is empty; no draw."
            )
        self.phase = GamePhase.PLAY_OR_PASS

    # ------------------------------------------------------------------
    # Setup helpers
    # ------------------------------------------------------------------

    def _setup_libraries(self) -> None:
        for player in self.players:
            deck = [
                Card(lt)
                for lt in self.LAND_TYPES
                for _ in range(self.CARDS_PER_TYPE)
            ]
            self.rand.shuffle(deck)
            player.library = deck

    def _draw_opening_hands(self) -> None:
        for player in self.players:
            for _ in range(self.OPENING_HAND_SIZE):
                player.draw()

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    def _log(self, message: str) -> None:
        entry = f"[T{self.turn_number}] {message}"
        self.event_log.append(entry)

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"BasicLandGame(turn={self.turn_number}, "
            f"active_player={self.active_player_idx}, "
            f"phase={self.phase.name}, "
            f"winner={self.winner})"
        )
