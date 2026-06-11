"""
Unit tests for the counter-spell logic in ai_type1_get_action and its helpers.

Covers:
  - AWAIT_COUNTER phase: allow vs. counter decisions
  - AWAIT_COUNTER_COUNTER phase: allow vs. counter decisions
  - _ai_type1_get_counter card-selection heuristics (higher score = more expendable)
  - Edge cases: minimum hand size, all-same-type hands, island-heavy hands
"""

import sys
import os
from random import Random

sys.path.insert(0, os.path.dirname(__file__))

from game_board import (
    Card, LandType, GamePhase, ActionType,
    PublicGameState, PublicPlayerState, GameAction,
)
from game_ai import ai_type1_get_action, _ai_type1_get_counter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_player(
    player_id: int,
    active: list[Card] | None = None,
    hand_size: int = 5,
) -> PublicPlayerState:
    return PublicPlayerState(
        player_id=player_id,
        library_size=40,
        hand_size=hand_size,
        revealed_hand=[],
        active=active or [],
        graveyard=[],
    )


def make_state(
    phase: GamePhase,
    active_player: int,
    pending_play: Card | None,
    player0_active: list[Card] | None = None,
    player1_active: list[Card] | None = None,
) -> PublicGameState:
    players = [
        make_player(0, active=player0_active or []),
        make_player(1, active=player1_active or []),
    ]
    return PublicGameState(
        phase=phase,
        active_player=active_player,
        turn_number=1,
        winner=None,
        pending_play=pending_play,
        players=players,
    )


# Five distinct land types for easy domain construction
ALL_TYPES = [LandType.FOREST, LandType.ISLAND, LandType.MOUNTAIN, LandType.PLAINS, LandType.SWAMP]

SEEDED_RAND = Random(42)


# ===========================================================================
# AWAIT_COUNTER — should the non-active player counter?
# ===========================================================================

class TestAwaitCounterDecision:
    """Player 1 is non-active and decides whether to counter player 0's play."""

    def _state_and_hands(
        self,
        pending_type: LandType,
        opponent_active: list[Card],
        player_hand: list[Card],
    ):
        """active_player=0, awaited player=1 (non-active)."""
        pending = Card(pending_type)
        state = make_state(
            phase=GamePhase.AWAIT_COUNTER,
            active_player=0,
            pending_play=pending,
            player0_active=opponent_active,  # player 0 is the opponent of awaited player 1
        )
        hands = [[], player_hand]  # only player 1's hand matters here
        return state, hands, pending

    # --- Should COUNTER ---

    def test_counter_when_opponent_would_complete_domain(self):
        """
        Opponent (player 0) already has 4 distinct types active.
        The pending play is the 5th — countering prevents their win.
        Player 1 has Island + another card, so can counter.
        """
        existing = [Card(t) for t in ALL_TYPES[:4]]  # 4 distinct types
        fifth_type = ALL_TYPES[4]
        hand = [Card(LandType.ISLAND), Card(LandType.FOREST)]

        state, hands, pending = self._state_and_hands(fifth_type, existing, hand)
        action = ai_type1_get_action(state, hands, SEEDED_RAND)

        assert action.action_type == ActionType.COUNTER_LAND

    def test_counter_uses_island_as_first_card(self):
        """The counter action must spend the Island as card_id."""
        existing = [Card(t) for t in ALL_TYPES[:4]]
        hand = [Card(LandType.ISLAND), Card(LandType.SWAMP)]

        state, hands, _ = self._state_and_hands(ALL_TYPES[4], existing, hand)
        action = ai_type1_get_action(state, hands, SEEDED_RAND)

        island = next(c for c in hand if c.land_type == LandType.ISLAND)
        assert action.card_id == island.card_id

    def test_counter_second_card_is_not_island(self):
        """The second card discarded must NOT be the Island itself."""
        existing = [Card(t) for t in ALL_TYPES[:4]]
        hand = [Card(LandType.ISLAND), Card(LandType.MOUNTAIN)]

        state, hands, _ = self._state_and_hands(ALL_TYPES[4], existing, hand)
        action = ai_type1_get_action(state, hands, SEEDED_RAND)

        island = next(c for c in hand if c.land_type == LandType.ISLAND)
        assert action.counter_second_card_id != island.card_id

    # --- Should ALLOW ---

    def test_allow_when_opponent_would_not_complete_domain(self):
        """Opponent has only 2 types; pending play does not complete domain. Allow."""
        existing = [Card(LandType.FOREST), Card(LandType.PLAINS)]
        hand = [Card(LandType.ISLAND), Card(LandType.SWAMP)]

        state, hands, _ = self._state_and_hands(LandType.MOUNTAIN, existing, hand)
        action = ai_type1_get_action(state, hands, SEEDED_RAND)

        assert action.action_type == ActionType.ALLOW_LAND

    def test_allow_when_no_island_in_hand(self):
        """Even if opponent would complete domain, can't counter without Island."""
        existing = [Card(t) for t in ALL_TYPES[:4]]
        hand = [Card(LandType.FOREST), Card(LandType.SWAMP)]

        state, hands, _ = self._state_and_hands(ALL_TYPES[4], existing, hand)
        action = ai_type1_get_action(state, hands, SEEDED_RAND)

        assert action.action_type == ActionType.ALLOW_LAND

    def test_allow_when_only_island_in_hand(self):
        """
        Player has Island but no second card to spend — _can_counter requires
        len(hand) > 1. Must allow.
        """
        existing = [Card(t) for t in ALL_TYPES[:4]]
        hand = [Card(LandType.ISLAND)]

        state, hands, _ = self._state_and_hands(ALL_TYPES[4], existing, hand)
        action = ai_type1_get_action(state, hands, SEEDED_RAND)

        assert action.action_type == ActionType.ALLOW_LAND

    def test_allow_when_opponent_active_empty(self):
        """Opponent has no active lands; pending play cannot complete domain."""
        hand = [Card(LandType.ISLAND), Card(LandType.FOREST)]
        state, hands, _ = self._state_and_hands(LandType.FOREST, [], hand)
        action = ai_type1_get_action(state, hands, SEEDED_RAND)

        assert action.action_type == ActionType.ALLOW_LAND

    def test_allow_when_pending_is_duplicate_type(self):
        """
        Opponent has 4 distinct types but the pending play duplicates one of them —
        adding it does NOT give 5 distinct types, so no counter.
        """
        existing = [Card(t) for t in ALL_TYPES[:4]]
        hand = [Card(LandType.ISLAND), Card(LandType.SWAMP)]
        # Pending is same type as an existing one
        state, hands, _ = self._state_and_hands(ALL_TYPES[0], existing, hand)
        action = ai_type1_get_action(state, hands, SEEDED_RAND)

        assert action.action_type == ActionType.ALLOW_LAND


# ===========================================================================
# AWAIT_COUNTER_COUNTER — active player decides whether to counter the counter
# ===========================================================================

class TestAwaitCounterCounterDecision:
    """
    Player 0 is active; they played a land, player 1 countered it, now player 0
    decides whether to counter-counter.

    In AWAIT_COUNTER_COUNTER the active player inspects their OWN active zone
    (state.phase != AWAIT_COUNTER, so the fixed condition uses player.active).
    A counter-counter is worth playing only when the pending card would complete
    player 0's own domain.
    """

    def _state_and_hands(
        self,
        pending_type: LandType,
        player0_active: list[Card],
        player1_active: list[Card],
        player0_hand: list[Card],
    ):
        """active_player=0, AWAIT_COUNTER_COUNTER → awaited player is 0."""
        pending = Card(pending_type)
        state = make_state(
            phase=GamePhase.AWAIT_COUNTER_COUNTER,
            active_player=0,
            pending_play=pending,
            player0_active=player0_active,
            player1_active=player1_active,
        )
        hands = [player0_hand, []]
        return state, hands, pending

    def test_allows_when_cannot_counter(self):
        """No Island in hand → must allow regardless of board state."""
        hand = [Card(LandType.FOREST), Card(LandType.SWAMP)]
        state, hands, _ = self._state_and_hands(
            LandType.MOUNTAIN,
            player0_active=[Card(t) for t in ALL_TYPES[:4]],
            player1_active=[],
            player0_hand=hand,
        )
        action = ai_type1_get_action(state, hands, SEEDED_RAND)
        assert action.action_type == ActionType.ALLOW_LAND

    def test_counter_counter_when_pending_completes_own_domain(self):
        """
        Player 0 has 4 distinct types active and the pending play is the 5th —
        countering the counter protects player 0's own win. Should counter.
        """
        p0_active = [Card(t) for t in ALL_TYPES[:4]]
        p1_active = [Card(LandType.FOREST), Card(LandType.PLAINS)]
        hand = [Card(LandType.ISLAND), Card(LandType.SWAMP)]
        pending_type = ALL_TYPES[4]

        state, hands, _ = self._state_and_hands(
            pending_type, p0_active, p1_active, hand
        )
        action = ai_type1_get_action(state, hands, SEEDED_RAND)
        assert action.action_type == ActionType.COUNTER_LAND

    def test_allows_when_pending_does_not_complete_own_domain(self):
        """
        Player 0 has only 2 distinct types active; the pending play is a 3rd.
        Resolving it would not win the game, so no counter-counter is warranted.
        Player 1's active zone is irrelevant — only player 0's zone is checked.
        """
        p0_active = [Card(LandType.FOREST), Card(LandType.PLAINS)]
        p1_active = [Card(t) for t in ALL_TYPES[:4]]  # opponent near domain — irrelevant
        hand = [Card(LandType.ISLAND), Card(LandType.SWAMP)]
        pending_type = ALL_TYPES[4]

        state, hands, _ = self._state_and_hands(
            pending_type, p0_active, p1_active, hand
        )
        action = ai_type1_get_action(state, hands, SEEDED_RAND)
        assert action.action_type == ActionType.ALLOW_LAND


# ===========================================================================
# _ai_type1_get_counter — second-card selection heuristics
# ===========================================================================

class TestAiType1GetCounterCardSelection:
    """Tests for the card-selection logic inside _ai_type1_get_counter."""

    def _run(self, active_cards: list[Card], hand: list[Card], seed: int = 0) -> GameAction:
        player = make_player(0, active=active_cards)
        return _ai_type1_get_counter(player, hand, Random(seed))

    def test_returns_counter_action_type(self):
        hand = [Card(LandType.ISLAND), Card(LandType.FOREST)]
        action = self._run([], hand)
        assert action.action_type == ActionType.COUNTER_LAND

    def test_island_is_first_card(self):
        hand = [Card(LandType.ISLAND), Card(LandType.SWAMP)]
        action = self._run([], hand)
        island = next(c for c in hand if c.land_type == LandType.ISLAND)
        assert action.card_id == island.card_id

    def test_second_card_different_from_island(self):
        hand = [Card(LandType.ISLAND), Card(LandType.MOUNTAIN)]
        action = self._run([], hand)
        island = next(c for c in hand if c.land_type == LandType.ISLAND)
        assert action.counter_second_card_id != island.card_id

    def test_prefers_type_already_in_active(self):
        """
        Higher score = less valuable (more expendable). Swamp is already in the
        active zone, so it scores higher (score 6 vs Forest's score 1) and is
        the correct card to spend as the second card.
        """
        swamp_in_hand = Card(LandType.SWAMP)
        forest_in_hand = Card(LandType.FOREST)
        island = Card(LandType.ISLAND)
        hand = [island, swamp_in_hand, forest_in_hand]
        active = [Card(LandType.SWAMP)]
        action = self._run(active, hand)
        assert action.counter_second_card_id == swamp_in_hand.card_id

    def test_avoids_spending_island_as_second_card_even_with_multiple_islands(self):
        """With two Islands in hand, the second card must still be non-Island."""
        island1 = Card(LandType.ISLAND)
        island2 = Card(LandType.ISLAND)
        other = Card(LandType.PLAINS)
        hand = [island1, island2, other]
        action = self._run([], hand)
        # One island is the first card; the other should NOT be the second card
        # because there is a non-Island available.
        assert action.counter_second_card_id == other.card_id

    def test_all_same_non_island_type(self):
        """All non-Island cards are the same type — picks one of them as second card."""
        island = Card(LandType.ISLAND)
        mountain1 = Card(LandType.MOUNTAIN)
        mountain2 = Card(LandType.MOUNTAIN)
        hand = [island, mountain1, mountain2]
        action = self._run([], hand)
        # Both mountains are equivalent; just verify a mountain is chosen
        non_island = {mountain1.card_id, mountain2.card_id}
        assert action.counter_second_card_id in non_island

    def test_minimum_hand_two_cards(self):
        """Edge case: exactly 2 cards (Island + one other). Must still work."""
        island = Card(LandType.ISLAND)
        other = Card(LandType.SWAMP)
        hand = [island, other]
        action = self._run([], hand)
        assert action.card_id == island.card_id
        assert action.counter_second_card_id == other.card_id

    def test_prefers_type_with_higher_count_in_hand(self):
        """
        Higher score = less valuable (more expendable). Two Swamps score higher
        (score 2) than one Forest (score 1), so a Swamp is the correct card to spend.
        """
        island = Card(LandType.ISLAND)
        forest1 = Card(LandType.FOREST)
        swamp1 = Card(LandType.SWAMP)
        swamp2 = Card(LandType.SWAMP)
        hand = [island, forest1, swamp1, swamp2]
        action = self._run([], hand, seed=0)
        swamp_ids = {swamp1.card_id, swamp2.card_id}
        assert action.counter_second_card_id in swamp_ids


# ===========================================================================
# Action structure validity
# ===========================================================================

class TestActionStructure:
    """Sanity checks on the returned GameAction objects."""

    def test_allow_land_has_correct_player_id(self):
        hand = [Card(LandType.FOREST), Card(LandType.PLAINS)]
        pending = Card(LandType.FOREST)
        state = make_state(
            phase=GamePhase.AWAIT_COUNTER,
            active_player=0,
            pending_play=pending,
            player0_active=[],
        )
        hands = [[], hand]
        action = ai_type1_get_action(state, hands, SEEDED_RAND)
        # Awaited player is 1 (non-active)
        assert action.player_id == 1

    def test_counter_land_has_correct_player_id(self):
        existing = [Card(t) for t in ALL_TYPES[:4]]
        hand = [Card(LandType.ISLAND), Card(LandType.SWAMP)]
        pending = Card(ALL_TYPES[4])
        state = make_state(
            phase=GamePhase.AWAIT_COUNTER,
            active_player=0,
            pending_play=pending,
            player0_active=existing,
        )
        hands = [[], hand]
        action = ai_type1_get_action(state, hands, SEEDED_RAND)
        assert action.action_type == ActionType.COUNTER_LAND
        assert action.player_id == 1

    def test_counter_land_second_card_is_in_hand(self):
        """Both cards used for the counter must actually be in the player's hand."""
        existing = [Card(t) for t in ALL_TYPES[:4]]
        hand = [Card(LandType.ISLAND), Card(LandType.MOUNTAIN)]
        pending = Card(ALL_TYPES[4])
        state = make_state(
            phase=GamePhase.AWAIT_COUNTER,
            active_player=0,
            pending_play=pending,
            player0_active=existing,
        )
        hands = [[], hand]
        action = ai_type1_get_action(state, hands, SEEDED_RAND)
        hand_ids = {c.card_id for c in hand}
        assert action.card_id in hand_ids
        assert action.counter_second_card_id in hand_ids
