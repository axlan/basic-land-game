"""
Tests for BasicLandGame state management.
Run with: python test_basic_land_game.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from game_board import (
    BasicLandGame, GameAction, ActionType, LandType,
    GamePhase, Card, PlayerState
)


def make_game(seed=42):
    return BasicLandGame(seed=seed)


def find_card(player: PlayerState, land_type: LandType) -> Card:
    """Find the first card of a given type in the player's hand."""
    for c in player.hand:
        if c.land_type == land_type:
            return c
    return None


def find_active_card(player: PlayerState, land_type: LandType) -> Card:
    for c in player.active:
        if c.land_type == land_type:
            return c
    return None


def find_graveyard_card(player: PlayerState, land_type: LandType = None) -> Card:
    for c in player.graveyard:
        if land_type is None or c.land_type == land_type:
            return c
    return None


# ---------------------------------------------------------------------------
# Helper: Play a land and allow it (no counter), returns ActionResult list
# ---------------------------------------------------------------------------

def play_and_allow(game: BasicLandGame, player_idx: int, card_id: str):
    r1 = game.apply_action(GameAction(ActionType.PLAY_LAND, player_idx, card_id=card_id))
    opponent_idx = 1 - player_idx
    r2 = game.apply_action(GameAction(ActionType.ALLOW_LAND, opponent_idx))
    return r1, r2


# ---------------------------------------------------------------------------
# Test: initial state
# ---------------------------------------------------------------------------

def test_initial_state():
    game = make_game()
    for p in game.players:
        assert len(p.hand) == 5, f"Expected 5 cards in hand, got {len(p.hand)}"
        assert len(p.library) == 45, f"Expected 45 cards in library, got {len(p.library)}"
        assert len(p.active) == 0
        assert len(p.graveyard) == 0
    assert game.active_player_idx in (0, 1)
    assert game.phase == GamePhase.PLAY_OR_PASS
    print("PASS test_initial_state")


# ---------------------------------------------------------------------------
# Test: wrong player cannot play
# ---------------------------------------------------------------------------

def test_wrong_player_rejected():
    game = make_game()
    non_active = 1 - game.active_player_idx
    card = game.players[non_active].hand[0]
    result = game.apply_action(GameAction(ActionType.PLAY_LAND, non_active, card_id=card.card_id))
    assert not result.success, "Non-active player should not be able to play"
    print("PASS test_wrong_player_rejected")


# ---------------------------------------------------------------------------
# Test: card not in hand is rejected
# ---------------------------------------------------------------------------

def test_card_not_in_hand_rejected():
    game = make_game()
    active = game.active_player_idx
    result = game.apply_action(GameAction(ActionType.PLAY_LAND, active, card_id="nonexistent-id"))
    assert not result.success
    print("PASS test_card_not_in_hand_rejected")


# ---------------------------------------------------------------------------
# Test: Island effect — draw a card
# ---------------------------------------------------------------------------

def test_island_draw():
    game = make_game()
    active = game.active_player_idx
    player = game.players[active]

    # Inject an Island if not in hand
    if not find_card(player, LandType.ISLAND):
        island = Card(LandType.ISLAND)
        player.hand.append(island)

    island = find_card(player, LandType.ISLAND)
    hand_size_before = len(player.hand)
    library_before   = len(player.library)

    r1, r2 = play_and_allow(game, active, island.card_id)
    assert r1.success and r2.success

    # Hand size: -1 (island played) +1 (draw) = same; but island is now in active
    assert len(player.active) >= 1
    assert any(c.land_type == LandType.ISLAND for c in player.active)
    # One card drawn from library
    assert len(player.library) == library_before - 1
    print("PASS test_island_draw")


# ---------------------------------------------------------------------------
# Test: Mountain effect — destroy opponent active land
# ---------------------------------------------------------------------------

def test_mountain_destroy():
    game = make_game()
    active = game.active_player_idx
    opponent_idx = 1 - active
    player   = game.players[active]
    opponent = game.players[opponent_idx]

    # Give opponent an active Plains
    plains = Card(LandType.PLAINS)
    opponent.active.append(plains)

    # Give active player a Mountain
    mountain = Card(LandType.MOUNTAIN)
    player.hand.append(mountain)

    r1, r2 = play_and_allow(game, active, mountain.card_id)
    assert r1.success and r2.success
    assert game.phase == GamePhase.RESOLVE_EFFECT

    # Now target the Plains
    r3 = game.apply_action(GameAction(ActionType.SPECIFY_TARGET, active, target_card_id=plains.card_id))
    assert r3.success, r3.message
    assert plains not in opponent.active
    assert plains in opponent.graveyard
    print("PASS test_mountain_destroy")


# ---------------------------------------------------------------------------
# Test: Mountain targeting invalid card rejected
# ---------------------------------------------------------------------------

def test_mountain_SPECIFY_TARGET():
    game = make_game()
    active = game.active_player_idx
    opponent_idx = 1 - active
    player   = game.players[active]
    opponent = game.players[opponent_idx]

    opponent.active.append(Card(LandType.SWAMP))
    mountain = Card(LandType.MOUNTAIN)
    player.hand.append(mountain)

    play_and_allow(game, active, mountain.card_id)

    r = game.apply_action(GameAction(ActionType.SPECIFY_TARGET, active, target_card_id="bad-id"))
    assert not r.success
    print("PASS test_mountain_SPECIFY_TARGET")


# ---------------------------------------------------------------------------
# Test: Forest effect — return graveyard card
# ---------------------------------------------------------------------------

def test_forest_regrowth():
    game = make_game()
    active = game.active_player_idx
    player = game.players[active]

    # Plant a card in own graveyard
    swamp = Card(LandType.SWAMP)
    player.graveyard.append(swamp)

    forest = Card(LandType.FOREST)
    player.hand.append(forest)

    r1, r2 = play_and_allow(game, active, forest.card_id)
    assert r1.success and r2.success
    assert game.phase == GamePhase.RESOLVE_EFFECT

    r3 = game.apply_action(GameAction(ActionType.SPECIFY_TARGET, active, target_card_id=swamp.card_id))
    assert r3.success, r3.message
    assert swamp not in player.graveyard
    assert swamp in player.hand
    print("PASS test_forest_regrowth")


# ---------------------------------------------------------------------------
# Test: Swamp effect — see and discard opponent hand card
# ---------------------------------------------------------------------------

def test_swamp_thoughtseize():
    game = make_game()
    active = game.active_player_idx
    opponent_idx = 1 - active
    player   = game.players[active]
    opponent = game.players[opponent_idx]

    swamp = Card(LandType.SWAMP)
    player.hand.append(swamp)

    target_card = opponent.hand[0]
    revealed_before_discard = len(opponent.revealed_card_ids)

    r1, r2 = play_and_allow(game, active, swamp.card_id)
    assert r1.success and r2.success
    assert game.phase == GamePhase.RESOLVE_EFFECT

    # Verify opponent's hand is revealed
    assert len(opponent.revealed_card_ids) > 0
    revealed_after_swamp = len(opponent.revealed_card_ids)

    r3 = game.apply_action(GameAction(ActionType.SPECIFY_TARGET, active, target_card_id=target_card.card_id))
    assert r3.success, r3.message
    assert target_card not in opponent.hand
    assert target_card in opponent.graveyard
    # After discarding one card from a revealed hand, the remaining cards stay revealed
    # (5 cards revealed initially, 1 discarded, so 4 remain revealed)
    assert len(game.public_state().players[opponent_idx].revealed_hand) == revealed_after_swamp - 1
    print("PASS test_swamp_thoughtseize")


# ---------------------------------------------------------------------------
# Test: Plains copies Island (draw)
# ---------------------------------------------------------------------------

def test_plains_copies_island():
    game = make_game()
    active = game.active_player_idx
    player = game.players[active]

    # Give active player an active Island to copy
    island_active = Card(LandType.ISLAND)
    player.active.append(island_active)

    plains = Card(LandType.PLAINS)
    player.hand.append(plains)

    library_before = len(player.library)
    r1, r2 = play_and_allow(game, active, plains.card_id)
    assert r1.success and r2.success

    # Plains goes to RESOLVE_EFFECT
    assert game.phase == GamePhase.RESOLVE_EFFECT

    r3 = game.apply_action(GameAction(ActionType.SPECIFY_TARGET, active, target_card_id=island_active.card_id))
    assert r3.success, r3.message
    # Should have drawn a card
    assert len(player.library) == library_before - 1
    print("PASS test_plains_copies_island")


# ---------------------------------------------------------------------------
# Test: Plains copies Mountain
# ---------------------------------------------------------------------------

def test_plains_copies_mountain():
    game = make_game()
    active = game.active_player_idx
    opponent_idx = 1 - active
    player   = game.players[active]
    opponent = game.players[opponent_idx]

    mountain_active = Card(LandType.MOUNTAIN)
    player.active.append(mountain_active)
    enemy_forest = Card(LandType.FOREST)
    opponent.active.append(enemy_forest)

    plains = Card(LandType.PLAINS)
    player.hand.append(plains)

    r1, r2 = play_and_allow(game, active, plains.card_id)
    assert r1.success and r2.success

    r3 = game.apply_action(GameAction(ActionType.SPECIFY_TARGET, active, target_card_id=mountain_active.card_id))
    assert r3.success, r3.message
    # Now in RESOLVE_EFFECT for Mountain
    assert game.phase == GamePhase.RESOLVE_EFFECT

    r4 = game.apply_action(GameAction(ActionType.SPECIFY_TARGET, active, target_card_id=enemy_forest.card_id))
    assert r4.success, r4.message
    assert enemy_forest in opponent.graveyard
    print("PASS test_plains_copies_mountain")


# ---------------------------------------------------------------------------
# Test: Island counter
# ---------------------------------------------------------------------------

def test_island_counter():
    game = make_game()
    active = game.active_player_idx
    opponent_idx = 1 - active
    player   = game.players[active]
    opponent = game.players[opponent_idx]

    # Give opponent Island + another land to counter with
    counter_island = Card(LandType.ISLAND)
    counter_other  = Card(LandType.SWAMP)
    opponent.hand.append(counter_island)
    opponent.hand.append(counter_other)

    # Active player tries to play a Mountain
    mountain = Card(LandType.MOUNTAIN)
    player.hand.append(mountain)

    r1 = game.apply_action(GameAction(ActionType.PLAY_LAND, active, card_id=mountain.card_id))
    assert r1.success
    assert game.phase == GamePhase.AWAIT_COUNTER

    r2 = game.apply_action(GameAction(
        ActionType.COUNTER_LAND, opponent_idx,
        card_id=counter_island.card_id,
        counter_second_card_id=counter_other.card_id,
    ))
    assert r2.success, r2.message
    assert game.phase == GamePhase.AWAIT_COUNTER_COUNTER

    r3 = game.apply_action(GameAction(
        ActionType.ALLOW_LAND, active
    ))
    assert r3.success, r3.message
    assert game.phase == GamePhase.PLAY_OR_PASS

    # Mountain should be in active player's graveyard
    assert mountain in player.graveyard
    # Counter cards in opponent's graveyard
    assert counter_island in opponent.graveyard
    assert counter_other  in opponent.graveyard
    print("PASS test_island_counter")

def test_2_island_counter():
    game = make_game()
    active = game.active_player_idx
    opponent_idx = 1 - active
    player   = game.players[active]
    opponent = game.players[opponent_idx]

    # Give opponent Island + another land to counter with
    counter_island = Card(LandType.ISLAND)
    counter_other  = Card(LandType.SWAMP)
    opponent.hand.append(counter_island)
    opponent.hand.append(counter_other)

    # Active player tries to play a Mountain
    mountain = Card(LandType.MOUNTAIN)
    counter_island2 = Card(LandType.ISLAND)
    counter_other2  = Card(LandType.SWAMP)
    player.hand.append(mountain)
    player.hand.append(counter_island2)
    player.hand.append(counter_other2)

    r1 = game.apply_action(GameAction(ActionType.PLAY_LAND, active, card_id=mountain.card_id))
    assert r1.success
    assert game.phase == GamePhase.AWAIT_COUNTER

    r2 = game.apply_action(GameAction(
        ActionType.COUNTER_LAND, opponent_idx,
        card_id=counter_island.card_id,
        counter_second_card_id=counter_other.card_id,
    ))
    assert r2.success, r2.message
    assert game.phase == GamePhase.AWAIT_COUNTER_COUNTER

    r3 = game.apply_action(GameAction(
        ActionType.COUNTER_LAND, active,
        card_id=counter_island2.card_id,
        counter_second_card_id=counter_other2.card_id,
    ))
    assert r3.success, r3.message
    assert game.phase == GamePhase.AWAIT_COUNTER

    r4 = game.apply_action(GameAction(
        ActionType.ALLOW_LAND, opponent_idx
    ))
    assert r4.success, r4.message
    assert game.phase == GamePhase.PLAY_OR_PASS

    # Mountain should be played
    assert mountain in player.active
    # Counter cards in graveyards
    assert counter_island in opponent.graveyard
    assert counter_other  in opponent.graveyard
    assert counter_island2 in player.graveyard
    assert counter_other2  in player.graveyard
    print("PASS test_island_counter")


def test_3_island_counter():
    game = make_game()
    active = game.active_player_idx
    opponent_idx = 1 - active
    player   = game.players[active]
    opponent = game.players[opponent_idx]

    # Give opponent Island + another land to counter with
    counter_island = Card(LandType.ISLAND)
    counter_other  = Card(LandType.SWAMP)
    counter_island3 = Card(LandType.ISLAND)
    counter_other3  = Card(LandType.PLAINS)
    opponent.hand.append(counter_island)
    opponent.hand.append(counter_other)
    opponent.hand.append(counter_island3)
    opponent.hand.append(counter_other3)

    # Active player tries to play a Mountain
    mountain = Card(LandType.MOUNTAIN)
    counter_island2 = Card(LandType.ISLAND)
    counter_other2  = Card(LandType.SWAMP)
    player.hand.append(mountain)
    player.hand.append(counter_island2)
    player.hand.append(counter_other2)

    r1 = game.apply_action(GameAction(ActionType.PLAY_LAND, active, card_id=mountain.card_id))
    assert r1.success
    assert game.phase == GamePhase.AWAIT_COUNTER

    r2 = game.apply_action(GameAction(
        ActionType.COUNTER_LAND, opponent_idx,
        card_id=counter_island.card_id,
        counter_second_card_id=counter_other.card_id,
    ))
    assert r2.success, r2.message
    assert game.phase == GamePhase.AWAIT_COUNTER_COUNTER

    r3 = game.apply_action(GameAction(
        ActionType.COUNTER_LAND, active,
        card_id=counter_island2.card_id,
        counter_second_card_id=counter_other2.card_id,
    ))
    assert r3.success, r3.message
    assert game.phase == GamePhase.AWAIT_COUNTER

    r4 = game.apply_action(GameAction(
        ActionType.COUNTER_LAND, opponent_idx,
        card_id=counter_island3.card_id,
        counter_second_card_id=counter_other3.card_id,
    ))
    assert r4.success, r4.message
    assert game.phase == GamePhase.AWAIT_COUNTER_COUNTER

    r5 = game.apply_action(GameAction(
        ActionType.ALLOW_LAND, active
    ))
    assert r5.success, r5.message
    assert game.phase == GamePhase.PLAY_OR_PASS

    # Mountain should be discarded
    assert mountain in player.graveyard
    # Counter cards in graveyards
    assert counter_island in opponent.graveyard
    assert counter_other  in opponent.graveyard
    assert counter_island3 in opponent.graveyard
    assert counter_other3  in opponent.graveyard
    assert counter_island2 in player.graveyard
    assert counter_other2  in player.graveyard
    print("PASS test_island_counter")


# ---------------------------------------------------------------------------
# Test: Counter with non-Island rejected
# ---------------------------------------------------------------------------

def test_counter_requires_island():
    game = make_game()
    active = game.active_player_idx
    opponent_idx = 1 - active
    player   = game.players[active]
    opponent = game.players[opponent_idx]

    mountain = Card(LandType.MOUNTAIN)
    player.hand.append(mountain)
    game.apply_action(GameAction(ActionType.PLAY_LAND, active, card_id=mountain.card_id))

    non_island = Card(LandType.SWAMP)
    second     = Card(LandType.FOREST)
    opponent.hand += [non_island, second]

    r = game.apply_action(GameAction(
        ActionType.COUNTER_LAND, opponent_idx,
        card_id=non_island.card_id,
        counter_second_card_id=second.card_id,
    ))
    assert not r.success, "Counter with non-Island should fail"
    print("PASS test_counter_requires_island")


# ---------------------------------------------------------------------------
# Test: Pass turn switches active player and draws
# ---------------------------------------------------------------------------

def test_pass_turn():
    game = make_game()
    active = game.active_player_idx
    next_player = 1 - active
    next_library_before = len(game.players[next_player].library)

    result = game.apply_action(GameAction(ActionType.PASS_TURN, active))
    assert result.success
    assert game.active_player_idx == next_player
    assert game.phase == GamePhase.PLAY_OR_PASS
    # Next player drew a card
    assert len(game.players[next_player].library) == next_library_before - 1
    print("PASS test_pass_turn")


# ---------------------------------------------------------------------------
# Test: Win condition — Domain (one of each land type)
# ---------------------------------------------------------------------------

def test_win_domain():
    game = make_game()
    active = game.active_player_idx
    player = game.players[active]

    # Put 4 different lands in active
    for lt in [LandType.FOREST, LandType.ISLAND, LandType.MOUNTAIN, LandType.SWAMP]:
        player.active.append(Card(lt))

    # Play the fifth (Plains)
    plains = Card(LandType.PLAINS)
    player.hand.append(plains)

    r1 = game.apply_action(GameAction(ActionType.PLAY_LAND, active, card_id=plains.card_id))
    assert r1.success
    r2 = game.apply_action(GameAction(ActionType.ALLOW_LAND, 1 - active))
    assert r2.success

    assert game.winner == active
    assert game.phase == GamePhase.GAME_OVER
    print("PASS test_win_domain")


# ---------------------------------------------------------------------------
# Test: Win condition — Mono (5 of same land)
# ---------------------------------------------------------------------------

def test_win_mono():
    game = make_game()
    active = game.active_player_idx
    player = game.players[active]

    for _ in range(4):
        player.active.append(Card(LandType.ISLAND))

    island = Card(LandType.ISLAND)
    player.hand.append(island)

    r1 = game.apply_action(GameAction(ActionType.PLAY_LAND, active, card_id=island.card_id))
    assert r1.success
    # Allow — Island goes to active; Island draw happens before win check... let's allow
    r2 = game.apply_action(GameAction(ActionType.ALLOW_LAND, 1 - active))
    # Win check happens right after land enters active, before draw
    assert game.winner == active
    assert game.phase == GamePhase.GAME_OVER
    print("PASS test_win_mono")


# ---------------------------------------------------------------------------
# Test: Actions rejected when game is over
# ---------------------------------------------------------------------------

def test_no_actions_after_game_over():
    game = make_game()
    active = game.active_player_idx
    game.winner = active
    game.phase  = GamePhase.GAME_OVER

    card = game.players[active].hand[0]
    r = game.apply_action(GameAction(ActionType.PLAY_LAND, active, card_id=card.card_id))
    assert not r.success
    print("PASS test_no_actions_after_game_over")


# ---------------------------------------------------------------------------
# Test: Mountain with no opponent active lands auto-resolves
# ---------------------------------------------------------------------------

def test_mountain_SPECIFY_TARGETs():
    game = make_game()
    active = game.active_player_idx
    player = game.players[active]
    # Ensure opponent has no active lands
    game.players[1 - active].active.clear()

    mountain = Card(LandType.MOUNTAIN)
    player.hand.append(mountain)

    r1, r2 = play_and_allow(game, active, mountain.card_id)
    assert r1.success and r2.success
    # Should auto-advance without requiring SPECIFY_TARGET
    assert game.phase == GamePhase.PLAY_OR_PASS
    print("PASS test_mountain_SPECIFY_TARGETs")


# ---------------------------------------------------------------------------
# Test: Plains cannot copy another Plains
# ---------------------------------------------------------------------------

def test_plains_cannot_copy_plains():
    """
    When only Plains are in the active zone, Plains auto-resolves with no
    effect (no valid non-Plains target exists). The turn should advance
    without ever entering RESOLVE_EFFECT.
    """
    game = make_game()
    active = game.active_player_idx
    player = game.players[active]

    # Put another Plains in active — the only active land
    other_plains = Card(LandType.PLAINS)
    player.active.append(other_plains)

    plains = Card(LandType.PLAINS)
    player.hand.append(plains)

    r1, r2 = play_and_allow(game, active, plains.card_id)
    assert r1.success and r2.success

    # Should NOT enter RESOLVE_EFFECT because no non-Plains active lands exist
    # The game auto-advances the turn
    assert game.phase == GamePhase.PLAY_OR_PASS, (
        f"Expected PLAY_OR_PASS (turn advanced), got {game.phase}"
    )
    print("PASS test_plains_cannot_copy_plains")


# ---------------------------------------------------------------------------
# Test: public_state hides hand contents
# ---------------------------------------------------------------------------

def test_public_state_hides_hand():
    game = make_game()
    state = game.public_state()
    for p_state in state.players:
        # hand_size is present but individual unrevealed cards are notin p_state
        assert len(p_state.revealed_hand) == 0  # nothing revealed yet
    print("PASS test_public_state_hides_hand")


# ---------------------------------------------------------------------------
# Test: player_hand returns private view
# ---------------------------------------------------------------------------

def test_player_hand_private():
    game = make_game()
    for pid in (0, 1):
        hand = game.player_hand(pid)
        assert len(hand) == len(game.players[pid].hand)
        for card_info in hand:
            assert "card_id" in card_info
            assert "land_type" in card_info
    print("PASS test_player_hand_private")


# ---------------------------------------------------------------------------
# Test: Forest can only return cards from active player's own graveyard
# ---------------------------------------------------------------------------

def test_forest_own_graveyard_only():
    """
    Forest should only return cards from the active player's own graveyard,
    not from the opponent's graveyard.
    """
    game = make_game()
    active = game.active_player_idx
    opponent_idx = 1 - active
    player = game.players[active]
    opponent = game.players[opponent_idx]

    # Put a card in opponent's graveyard
    opponent_card = Card(LandType.SWAMP)
    opponent.graveyard.append(opponent_card)

    # Put a card in active player's graveyard
    own_card = Card(LandType.ISLAND)
    player.graveyard.append(own_card)

    # Play Forest
    forest = Card(LandType.FOREST)
    player.hand.append(forest)

    r1, r2 = play_and_allow(game, active, forest.card_id)
    assert r1.success and r2.success
    assert game.phase == GamePhase.RESOLVE_EFFECT

    # Try to target opponent's card — should fail
    r3 = game.apply_action(
        GameAction(ActionType.SPECIFY_TARGET, active, target_card_id=opponent_card.card_id)
    )
    assert not r3.success, "Should not allow returning opponent's card"
    assert opponent_card in opponent.graveyard  # Card should still be there

    # Target own card — should succeed
    r4 = game.apply_action(
        GameAction(ActionType.SPECIFY_TARGET, active, target_card_id=own_card.card_id)
    )
    assert r4.success, r4.message
    assert own_card in player.hand
    assert own_card not in player.graveyard
    print("PASS test_forest_own_graveyard_only")


# ---------------------------------------------------------------------------
# Test: Card returned from graveyard via Forest is marked as revealed
# ---------------------------------------------------------------------------

def test_forest_returned_card_revealed():
    """
    When a card is returned from graveyard to hand via Forest effect,
    it should be marked as revealed (visible to opponent).
    """
    game = make_game()
    active = game.active_player_idx
    player = game.players[active]

    # Put a card in active player's graveyard
    card = Card(LandType.SWAMP)
    player.graveyard.append(card)

    # Initially the card should not be revealed in hand
    # (even though it came from graveyard, where it's public)
    assert card.card_id not in player.revealed_card_ids

    # Play Forest
    forest = Card(LandType.FOREST)
    player.hand.append(forest)

    r1, r2 = play_and_allow(game, active, forest.card_id)
    assert r1.success and r2.success

    # Apply Forest effect to return the card
    r3 = game.apply_action(
        GameAction(ActionType.SPECIFY_TARGET, active, target_card_id=card.card_id)
    )
    assert r3.success, r3.message
    assert card in player.hand

    # The card should now be marked as revealed
    assert card.card_id in player.revealed_card_ids, (
        "Card returned from graveyard should be marked as revealed"
    )
    print("PASS test_forest_returned_card_revealed")


# ---------------------------------------------------------------------------
# Run all tests
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_initial_state,
        test_wrong_player_rejected,
        test_card_not_in_hand_rejected,
        test_island_draw,
        test_mountain_destroy,
        test_mountain_SPECIFY_TARGET,
        test_forest_regrowth,
        test_swamp_thoughtseize,
        test_plains_copies_island,
        test_plains_copies_mountain,
        test_island_counter,
        test_2_island_counter,
        test_3_island_counter,
        test_counter_requires_island,
        test_pass_turn,
        test_win_domain,
        test_win_mono,
        test_no_actions_after_game_over,
        test_mountain_SPECIFY_TARGETs,
        test_plains_cannot_copy_plains,
        test_public_state_hides_hand,
        test_player_hand_private,
        test_forest_own_graveyard_only,
        test_forest_returned_card_revealed,
    ]

    failures = []
    for test in tests:
        try:
            test()
        except Exception as exc:
            print(f"FAIL {test.__name__}: {exc}")
            failures.append(test.__name__)

    print(f"\n{'='*50}")
    print(f"Results: {len(tests) - len(failures)}/{len(tests)} passed")
    if failures:
        print(f"Failed: {failures}")
        sys.exit(1)
    else:
        print("All tests passed!")
