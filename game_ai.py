from random import Random
from typing import Optional

from game_board import PublicGameState, GameAction, Card, LandType, GamePhase, ActionType, PublicPlayerState

def _count_type(cards: list[Card], type: LandType) -> int:
    return sum(c.land_type == type for c in cards)

def _has_type(cards: list[Card], type: LandType) -> bool:
    return any(c.land_type == type for c in cards)

def _get_first_of_type(cards: list[Card], type: LandType) -> Card:
    return next(c for c in cards if c.land_type == type)

def _can_counter(hand: list[Card]) -> bool:
    return _has_type(hand, LandType.ISLAND) and len(hand) > 1

def _land_type_set(cards: list[Card]) -> set[LandType]:
    return set(c.land_type for c in cards)

def _ai_type1_mountain_target(opponent: PublicPlayerState, rand: Random) -> Optional[str]:
    if len(opponent.active) == 0:
        return None
    
    types = _land_type_set(opponent.active)
    types_in_hand = _land_type_set(opponent.revealed_hand)

    singleton_types = [ t for t in types if _count_type(opponent.active, t) == 1 ]
    types_not_in_hand = [t for t in types if t not in types_in_hand]
    both = [t for t in singleton_types if t in types_not_in_hand]

    target_list = both if both else \
        singleton_types if singleton_types else \
        list(types)

    return _get_first_of_type(opponent.active, rand.sample(target_list, 1)[0]).card_id



def _ai_type1_swamp_target(opponent: PublicPlayerState, rand: Random) -> Optional[str]:
    """
    Discard the opponent hand card that hurts them most.
    Priority: a type not yet in their active zone (denies new coverage), and
    among those prefer types also absent from the rest of their revealed hand
    (least recoverable). Falls back to any revealed card, then None if nothing
    is visible.
    """
    if not opponent.revealed_hand:
        return None
 
    active_types = _land_type_set(opponent.active)
    revealed = opponent.revealed_hand
 
    # Cards that would add a new type to opponent's active zone
    new_coverage = [c for c in revealed if c.land_type not in active_types]
 
    candidate_cards = new_coverage if new_coverage else list(revealed)
 
    # Among candidates, prefer types with only one copy in the revealed hand
    # (harder for the opponent to replace)
    singleton_types = {
        t for t in _land_type_set(candidate_cards)
        if _count_type(revealed, t) == 1
    }
    singletons = [c for c in candidate_cards if c.land_type in singleton_types]
    candidate_cards = singletons if singletons else candidate_cards
 
    return rand.sample(candidate_cards, 1)[0].card_id
 
 
def _ai_type1_forest_target(player: PublicPlayerState, hand: list[Card], rand: Random) -> Optional[str]:
    """
    Return the graveyard card that most improves the player's unique type coverage.
    Priority:
      1. A type not already in active zone or hand (genuine new coverage).
      2. A type in active zone but not in hand (rebuilds a lost type).
      3. Any card (at least gets something back).
    """
    if len(player.graveyard) == 0:
        return None
 
    hand_types = _land_type_set(hand)
    active_types = _land_type_set(player.active)
 
    # Tier 1: type not in active and not in hand — brand new coverage
    tier1 = [c for c in player.graveyard
             if c.land_type not in active_types and c.land_type not in hand_types]
    # Tier 2: type in active but not in hand — rebuilds something we lost
    tier2 = [c for c in player.graveyard
             if c.land_type in active_types and c.land_type not in hand_types]
 
    candidates = tier1 if tier1 else (tier2 if tier2 else player.graveyard)

    return rand.sample(candidates, 1)[0].card_id
 
 
def _ai_type1_plains_target(player: PublicPlayerState, opponent: PublicPlayerState, hand: list[Card], rand: Random) -> Optional[str]:
    """
    Choose which active non-Plains land to copy, picking the most impactful
    effect available given the current board state.
 
    Effect priority:
      Mountain — removes an opponent active land (best when opponent has lands).
      Swamp    — discards from opponent hand (best when opponent has cards).
      Forest   — recurs a graveyard card (useful when any graveyard is non-empty).
      Island   — draws a card (always useful as a fallback).
 
    Returns the card_id of the chosen active land, or None if no valid target exists.
    """
    copyable = [c for c in player.active if c.land_type != LandType.PLAINS]
    if not copyable:
        return None
 
    copyable_types = _land_type_set(copyable)
 
    # Build a priority-ordered list of desirable effects
    priority: list[LandType] = []
    if LandType.MOUNTAIN in copyable_types and len(opponent.active) > 0:
        priority.append(LandType.MOUNTAIN)
    if LandType.SWAMP in copyable_types and opponent.hand_size > 0:
        priority.append(LandType.SWAMP)
    if LandType.FOREST in copyable_types and player.graveyard:
        priority.append(LandType.FOREST)
    if LandType.ISLAND in copyable_types:
        priority.append(LandType.ISLAND)
 
    # Fall back to any copyable land if nothing in the priority list matched
    if not priority:
        candidates = list(copyable)
        return rand.sample(candidates, 1)[0].card_id
 
    chosen_type = priority[0]
    candidates = [c for c in copyable if c.land_type == chosen_type]
    return rand.sample(candidates,1)[0].card_id


def _ai_type1_get_counter(player: PublicPlayerState, hand: list[Card], rand: Random)-> GameAction:
    cards = list(hand) 
    island_card = _get_first_of_type(cards, LandType.ISLAND)
    cards.remove(island_card)

    # If all cards are same type choose first
    if len(_land_type_set(cards)) == 1:
        second_card = cards[0]
    # Prioritize saving islands, or cards needed to win
    else:
        cards = [c for c in cards if c.land_type != LandType.ISLAND]
        types = list(_land_type_set(cards))
        # Shuffle the types to randomize priority
        rand.shuffle(types)
        # higher score = more expendable
        best_score = 0
        best_type = types[0]
        for land_type in types:
            score = 0
            if _has_type(player.active, land_type):
                score += 5
            score += _count_type(cards, land_type)
            if score > best_score:
                best_score = score
                best_type = land_type

        second_card = _get_first_of_type(cards, best_type)

    return GameAction(ActionType.COUNTER_LAND, player.player_id, card_id=island_card.card_id, counter_second_card_id=second_card.card_id)

def ai_type1_get_action(state: PublicGameState, hands: list[list[Card]], rand=Random()) -> GameAction:
    """ Basic heuristics guide AI behavior. It only considers domain victory. """
    player_idx = state.get_awaited_player()
    player = state.players[player_idx]
    opponent = state.players[1 - player_idx]
    hand = hands[player_idx]

    if state.phase in (GamePhase.AWAIT_COUNTER, GamePhase.AWAIT_COUNTER_COUNTER):
        assert state.pending_play is not None
        # Only use counters to either prevent opponent from winning, or to secure own win by countering a counter.
        active = opponent.active if state.phase == GamePhase.AWAIT_COUNTER else player.active
        if _can_counter(hand) and len(_land_type_set(active + [state.pending_play])) == 5:
            return _ai_type1_get_counter(player, hand, rand)
        else:
            return GameAction(ActionType.ALLOW_LAND, player_idx)
    elif state.phase == GamePhase.PLAY_OR_PASS:
        hand_types = _land_type_set(hand)
        
        # Prioritize playing cards not yet in active zone
        not_in_play = set(hand_types)
        not_in_play.difference_update(_land_type_set(player.active))
        if len(not_in_play) > 0:
            hand_types = not_in_play

        best_plays = list(hand_types)
        if LandType.ISLAND in hand_types:
            best_plays.remove(LandType.ISLAND)
        if LandType.SWAMP in hand_types and opponent.hand_size == 0:
            best_plays.remove(LandType.SWAMP)
        if LandType.MOUNTAIN in hand_types and len(opponent.active) == 0:
            best_plays.remove(LandType.MOUNTAIN)
        if LandType.FOREST in hand_types and len(player.graveyard) == 0:
            best_plays.remove(LandType.FOREST)
        if LandType.PLAINS in hand_types and _ai_type1_plains_target(player, opponent, hand, rand) is None:
            best_plays.remove(LandType.PLAINS)
        
        if len(best_plays) == 0:
            best_plays = list(hand_types)

        card_id = _get_first_of_type(hand, rand.sample(best_plays, 1)[0]).card_id
        return GameAction(ActionType.PLAY_LAND, player_idx, card_id=card_id)

    elif state.phase == GamePhase.RESOLVE_EFFECT:
        assert state.pending_play is not None
        card_id = {
            LandType.MOUNTAIN: _ai_type1_mountain_target(opponent, rand),
            LandType.SWAMP: _ai_type1_swamp_target(opponent, rand),
            LandType.FOREST: _ai_type1_forest_target(player, hand, rand),
            LandType.PLAINS: _ai_type1_plains_target(player, opponent, hand, rand)
        }[state.pending_play.land_type]
        return GameAction(ActionType.SPECIFY_TARGET, player_idx, card_id=state.pending_play.card_id, target_card_id=card_id)
    
    raise RuntimeError(f"AI asked for move for unexpected phase {state.phase.name}")
