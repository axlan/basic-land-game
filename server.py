#!/usr/bin/env python3

"""
Basic Land Game — FastAPI Server
=================================

REST endpoints
--------------
POST /lobby/join              Register a player name and enter the lobby.
GET  /lobby/waiting           List names currently waiting for an opponent.
POST /lobby/challenge         Challenge a waiting player → creates a game, returns game_id.
DELETE /lobby/leave           Leave the lobby without starting a game.
POST /games/vs-ai             Start a solo game against the built-in AI instantly.
                              Returns game_id + player_token — no lobby step needed.

Game endpoints (all require ?player_token=<token>)
---------------------------------------------------
GET  /games/{game_id}/state   Return the game state visible to this player.
POST /games/{game_id}/action  Submit a game action.

WebSocket
---------
WS   /lobby/ws?player_token=<token>
     Lobby-level events: opponent joined, challenge received, game started.

WS   /games/{game_id}/ws?player_token=<token>
     Game-level push. Also accepts action JSON from the client.

Authentication
--------------
On /lobby/join the server returns a player_token (opaque UUID).  Every
subsequent request and WebSocket connection must supply this token.  The
token identifies the player and determines which player_id (0 or 1) they
are in a given game.

Wire formats
------------
All messages (REST responses and WebSocket pushes) are JSON.  WebSocket
messages are always objects with a "type" discriminator field.

WebSocket message types (server → client):
  lobby_update      — waiting list changed
  game_started      — a game was created; contains game_id
  game_state        — full game state snapshot (after every action)
  action_result     — success/failure of the last action submitted
  pong              — response to a client "ping" keepalive
  error             — something went wrong
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
import logging
from random import Random
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from game_board import (
    ActionResult,
    ActionType,
    BasicLandGame,
    GameAction,
    GamePhase,
)
from game_ai import ai_type1_get_action

# ===========================================================================
# Timeout constants
# ===========================================================================

LOBBY_IDLE_SECONDS = 15 * 60   # 15 minutes — kick from waiting lobby
TURN_IDLE_SECONDS  = 15 * 60   # 15 minutes — auto-forfeit idle turn

# ===========================================================================
# Application
# ===========================================================================

app = FastAPI(
    title="Basic Land Game Server",
    description="Multiplayer server for the Basic Land Game (MTG variant)",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===========================================================================
# In-memory store  (swap for a real DB in production)
# ===========================================================================

class PlayerRecord:
    """Runtime record for a connected player."""
    def __init__(self, name: str, reserved_for_name: Optional[str] = None):
        self.player_id:        str           = str(uuid.uuid4())
        self.token:            str           = str(uuid.uuid4())
        self.name:             str           = name
        self.reserved_for_name: Optional[str] = reserved_for_name  # only this opponent can challenge
        self.game_id:          Optional[str] = None   # set when in a game
        self.game_seat:        Optional[int] = None   # 0 or 1
        self.joined_at:        float         = time.monotonic()  # for lobby idle timeout
        self.is_ai:            bool          = False


def _make_ai_player() -> PlayerRecord:
    """Create a placeholder PlayerRecord representing the AI opponent."""
    record = PlayerRecord(name="AI Opponent")
    record.is_ai = True
    return record


class GameRecord:
    """Container for a running game and its WebSocket connections."""
    def __init__(self, game_id: str, player0: PlayerRecord, player1: PlayerRecord):
        self.game_id:  str           = game_id
        self.players:  list[PlayerRecord] = [player0, player1]
        self.game:     BasicLandGame = BasicLandGame()
        # seat index → list of open WebSocket connections (reconnects allowed)
        self.ws_connections: dict[int, list[WebSocket]] = {0: [], 1: []}
        # Track how many event-log entries each seat has already received
        self.log_sent: dict[int, int] = {0: 0, 1: 0}
        # Timestamp of when the current turn began, for idle-turn enforcement
        self.turn_started_at: float = time.monotonic()
        # Is the opponent in this game an AI
        self.has_ai_opponent = False


# Global in-process store
_players_by_token:  dict[str, PlayerRecord]       = {}  # token   → record
_waiting_players:   dict[str, PlayerRecord]       = {}  # pid     → record
_games:             dict[str, GameRecord]         = {}  # game_id → record
_lobby_connections: dict[str, list[WebSocket]]    = {}  # pid     → ws list


# ===========================================================================
# Internal helpers
# ===========================================================================

def _require_player(token: str) -> PlayerRecord:
    p = _players_by_token.get(token)
    if p is None:
        raise HTTPException(status_code=401, detail="Invalid player token.")
    return p


def _require_game(game_id: str) -> GameRecord:
    g = _games.get(game_id)
    if g is None:
        raise HTTPException(status_code=404, detail=f"Game {game_id} not found.")
    return g


def _seat_of(record: GameRecord, player: PlayerRecord) -> int:
    for i, p in enumerate(record.players):
        if p.player_id == player.player_id:
            return i
    raise HTTPException(status_code=403, detail="You are not in this game.")


def _whose_turn_label(record: GameRecord, seat: int) -> str:
    """Return 'you', 'opponent', or 'game_over' from this seat's perspective."""
    game = record.game
    if game.phase == GamePhase.GAME_OVER:
        return "game_over"
    if game.phase == GamePhase.AWAIT_COUNTER:
        # Non-active player decides whether to counter
        return "you" if seat != game.active_player_idx else "opponent"
    return "you" if seat == game.active_player_idx else "opponent"


def _winner_name(record: GameRecord) -> Optional[str]:
    if record.game.winner is None:
        return None
    return record.players[record.game.winner].name


def _public_state_for(record: GameRecord, seat: int) -> dict:
    """
    Build the state payload for a given seat.
    Own hand is fully visible; opponent's hand shows only size + revealed cards.
    New event-log entries since the last call are included.
    """
    game  = record.game
    base  = game.public_state().to_dict()

    # Add player names
    for i, ps in enumerate(base["players"]):
        ps["name"] = record.players[i].name

    # Private hand for this seat
    base["my_seat"] = seat
    base["my_hand"] = [c.to_dict() for c in game.player_hand(seat)]

    # Convenience: whose turn it is from this seat's perspective
    base["whose_turn"]   = _whose_turn_label(record, seat)
    base["winner_name"]  = _winner_name(record)

    # Incremental event log
    base["new_events"]  = game.event_log[record.log_sent[seat]:]
    record.log_sent[seat] = len(game.event_log)

    return base


async def _push_game_state(record: GameRecord) -> None:
    """Push a game_state message to every connected WebSocket in this game."""
    for seat in (0, 1):
        payload = {
            "type":  "game_state",
            "state": _public_state_for(record, seat),
        }
        dead: list[WebSocket] = []
        for ws in list(record.ws_connections[seat]):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            record.ws_connections[seat].remove(ws)


def _visible_waiting(viewer: PlayerRecord) -> list[dict]:
    """
    Return the waiting-list entries visible to *viewer*.
    A slot is visible when:
      - it has no reservation (open challenge), OR
      - its reservation names the viewer exactly (case-insensitive).
    The viewer's own entry is always excluded.
    """
    result = []
    for p in _waiting_players.values():
        if p.player_id == viewer.player_id:
            continue
        if p.reserved_for_name is not None and \
                p.reserved_for_name.lower() != viewer.name.lower():
            continue
        result.append({
            "player_id":         p.player_id,
            "name":              p.name,
            "reserved_for_name": p.reserved_for_name,
        })
    return result


async def _push_lobby_update() -> None:
    """Push a personalised waiting list to every connected lobby WebSocket."""
    dead_players: list[str] = []
    for pid, ws_list in list(_lobby_connections.items()):
        viewer = next(
            (p for p in _players_by_token.values() if p.player_id == pid), None
        )
        if viewer is None:
            dead_players.append(pid)
            continue
        payload = {"type": "lobby_update", "waiting": _visible_waiting(viewer)}
        dead_ws: list[WebSocket] = []
        for ws in list(ws_list):
            try:
                await ws.send_json(payload)
            except Exception:
                dead_ws.append(ws)
        for ws in dead_ws:
            ws_list.remove(ws)
        if not ws_list:
            dead_players.append(pid)
    for pid in dead_players:
        _lobby_connections.pop(pid, None)


# ===========================================================================
# State cleanup helpers
# ===========================================================================

async def _evict_lobby_player(player: PlayerRecord, reason: str = "timeout") -> None:
    """
    Remove a player from every in-memory store and notify their lobby
    WebSocket connections.  Safe to call even if the player is not waiting.
    """
    _waiting_players.pop(player.player_id, None)
    _players_by_token.pop(player.token, None)

    msg = {"type": "session_timeout", "reason": reason}
    for ws in list(_lobby_connections.get(player.player_id, [])):
        try:
            await ws.send_json(msg)
            await ws.close()
        except Exception:
            pass
    _lobby_connections.pop(player.player_id, None)


async def _evict_game_players(record: GameRecord, timed_out_seat: int) -> None:
    """
    Force-forfeit the idle player, push the final game_state to both seats,
    then send a session_timeout notification and clean up all state.
    AI seats are never evicted — only human players can time out.
    """
    # Never evict the AI seat — it can't actually be idle.
    if record.players[timed_out_seat].is_ai:
        return

    game_id = record.game_id

    # Apply forfeit on behalf of the idle player
    forfeit_action = GameAction(
        action_type=ActionType.FORFEIT,
        player_id=timed_out_seat,
    )
    record.game.apply_action(forfeit_action)

    # Push the final game state before we tear anything down
    await _push_game_state(record)

    # Notify both players with a session_timeout so the frontend can redirect
    idle_name    = record.players[timed_out_seat].name
    other_seat   = 1 - timed_out_seat
    messages = {
        timed_out_seat: {
            "type":   "session_timeout",
            "reason": "You were removed for inactivity.",
        },
        other_seat: {
            "type":   "session_timeout",
            "reason": f"{idle_name} was removed for inactivity. You have been returned to the lobby.",
        },
    }

    for seat in (0, 1):
        for ws in list(record.ws_connections.get(seat, [])):
            try:
                await ws.send_json(messages[seat])
                await ws.close()
            except Exception:
                pass
        record.ws_connections[seat].clear()

    # Tear down player and game records
    for player in record.players:
        _waiting_players.pop(player.player_id, None)
        _players_by_token.pop(player.token, None)
        _lobby_connections.pop(player.player_id, None)

    _games.pop(game_id, None)


# ===========================================================================
# AI turn helper
# ===========================================================================

async def _maybe_run_ai_turn(record: GameRecord) -> None:
    """
    If the game has an AI player and it is currently the AI's turn, keep
    applying AI actions until control returns to the human or the game ends.
    Each accepted action resets the idle-turn clock (same as a human action).
    """
    if not record.has_ai_opponent:
        return
    game = record.game

    # Determine which seat the AI occupies (always seat 1 for vs-ai games).
    ai_seat = next(
        i for i, p in enumerate(record.players) if p.is_ai
    )

    MAX_AI_STEPS = 20  # safety cap — prevents infinite loops on a bug
    for _ in range(MAX_AI_STEPS):
        if game.phase == GamePhase.GAME_OVER:
            break

        public_state = game.public_state()

        awaited = public_state.get_awaited_player()
        if awaited != ai_seat:
            break

        hands = [game.player_hand(0), game.player_hand(1)]
        action = ai_type1_get_action(public_state, hands)
        result = game.apply_action(action)
        if result.success:
            record.turn_started_at = time.monotonic()
            # Push update to WebSocket clients (non-blocking)
            asyncio.create_task(_push_game_state(record))
        else:
            # AI produced an invalid action — log and bail to avoid a spin-loop
            logging.getLogger(__name__).error(
                "AI produced invalid action %s in game %s: %s",
                action, record.game_id, result.message,
            )
            break


# ===========================================================================
# Background timeout reaper
# ===========================================================================

async def _timeout_reaper() -> None:
    """
    Runs forever (started on application startup).  Every 30 seconds it:
      1. Evicts lobby players idle for > LOBBY_IDLE_SECONDS.
      2. Auto-forfeits in-game players whose turn has lasted > TURN_IDLE_SECONDS.
    """
    while True:
        await asyncio.sleep(30)
        now = time.monotonic()

        # --- Lobby idle evictions ---
        for player in list(_waiting_players.values()):
            if now - player.joined_at > LOBBY_IDLE_SECONDS:
                await _evict_lobby_player(
                    player,
                    reason="You were removed from the lobby after 15 minutes of inactivity.",
                )
        # Refresh lobby list if anyone was evicted
        if _lobby_connections:
            await _push_lobby_update()

        # --- In-game turn idle forfeits ---
        for record in list(_games.values()):
            if record.game.phase == GamePhase.GAME_OVER:
                continue
            if now - record.turn_started_at > TURN_IDLE_SECONDS:
                idle_seat = record.game.public_state().get_awaited_player()
                # Skip AI-controlled seats — they never idle
                if record.players[idle_seat].is_ai:
                    continue
                await _evict_game_players(record, timed_out_seat=idle_seat)


@app.on_event("startup")
async def _start_reaper() -> None:
    asyncio.create_task(_timeout_reaper())


# ===========================================================================
# Pydantic models
# ===========================================================================

class JoinRequest(BaseModel):
    name:              str
    reserved_for_name: Optional[str] = None  # if set, only this named player sees the slot

class JoinResponse(BaseModel):
    player_id:    str
    player_token: str
    name:         str

class WaitingPlayer(BaseModel):
    player_id:         str
    name:              str
    reserved_for_name: Optional[str] = None  # set when the slot is private

class WaitingListResponse(BaseModel):
    waiting: list[WaitingPlayer]

class ChallengeRequest(BaseModel):
    opponent_player_id: str

class ChallengeResponse(BaseModel):
    game_id:       str
    your_seat:     int
    opponent_name: str
    message:       str

class VsAiResponse(BaseModel):
    game_id:      str
    your_seat:    int
    player_token: str
    message:      str

class ActionRequest(BaseModel):
    action_type:            str
    card_id:                Optional[str] = None
    counter_second_card_id: Optional[str] = None
    target_card_id:         Optional[str] = None

class ActionResponse(BaseModel):
    success:   bool
    message:   str
    new_state: dict


# ===========================================================================
# Action-type lookup (accepts any case)
# ===========================================================================

_ACTION_MAP: dict[str, ActionType] = {at.name.upper(): at for at in ActionType}


def _parse_action_type(raw: str) -> ActionType:
    at = _ACTION_MAP.get(raw.upper())
    if at is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown action_type '{raw}'. Valid: {sorted(_ACTION_MAP.keys())}",
        )
    return at

# ===========================================================================
# Lobby — REST
# ===========================================================================

@app.post("/lobby/join", response_model=JoinResponse, tags=["Lobby"])
async def join_lobby(body: JoinRequest):
    """
    Register a display name and enter the waiting lobby.
    Returns a **player_token** — keep this secret and include it with every
    subsequent request as ?player_token=<token>.

    A player should call this only once per session.  Calling it again creates
    a new independent identity.

    Pass **reserved_for_name** to create a private slot: only the player with
    that display name will see your entry in the lobby.
    """
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name must not be blank.")
    if len(name) > 32:
        raise HTTPException(status_code=400, detail="Name must be ≤ 32 characters.")

    reserved_for = body.reserved_for_name.strip() if body.reserved_for_name else None
    if reserved_for and reserved_for.lower() == name.lower():
        raise HTTPException(status_code=400, detail="You cannot reserve a slot for yourself.")

    for p in _waiting_players.values():
        if p.name.lower() == name.lower():
            raise HTTPException(
                status_code=409,
                detail=f"The name '{name}' is already taken in the lobby.",
            )

    record = PlayerRecord(name=name, reserved_for_name=reserved_for)
    _players_by_token[record.token] = record
    _waiting_players[record.player_id] = record

    await _push_lobby_update()

    return JoinResponse(
        player_id=record.player_id,
        player_token=record.token,
        name=record.name,
    )


@app.get("/lobby/waiting", response_model=WaitingListResponse, tags=["Lobby"])
async def list_waiting(player_token: str = Query(...)):
    """
    List players currently waiting for an opponent, filtered for the caller.
    Open slots (no reservation) are visible to everyone.
    Reserved slots are only visible to the named opponent.
    """
    player = _require_player(player_token)
    return WaitingListResponse(
        waiting=[
            WaitingPlayer(
                player_id=p["player_id"],
                name=p["name"],
                reserved_for_name=p["reserved_for_name"],
            )
            for p in _visible_waiting(player)
        ]
    )


@app.post("/lobby/challenge", response_model=ChallengeResponse, tags=["Lobby"])
async def challenge_opponent(body: ChallengeRequest, player_token: str = Query(...)):
    """
    Challenge a waiting player by their **player_id**.
    Both players are immediately removed from the lobby and a new game is
    created.  The challenger is assigned seat 0; the opponent seat 1.
    Which seat actually goes first is determined randomly by the game engine.

    The opponent will receive a **game_started** message on their lobby
    WebSocket connection if they have one open.
    """
    challenger = _require_player(player_token)

    if challenger.game_id is not None:
        raise HTTPException(status_code=409, detail="You are already in a game.")

    opponent = _waiting_players.get(body.opponent_player_id)
    if opponent is None:
        raise HTTPException(status_code=404, detail="Opponent not found in lobby.")
    if opponent.player_id == challenger.player_id:
        raise HTTPException(status_code=400, detail="You cannot challenge yourself.")
    if opponent.reserved_for_name is not None and             opponent.reserved_for_name.lower() != challenger.name.lower():
        raise HTTPException(
            status_code=403,
            detail=f"That player is waiting for a specific opponent.",
        )

    _waiting_players.pop(challenger.player_id, None)
    _waiting_players.pop(opponent.player_id, None)

    game_id = str(uuid.uuid4())
    record  = GameRecord(game_id=game_id, player0=challenger, player1=opponent)
    _games[game_id] = record

    challenger.game_id   = game_id
    challenger.game_seat = 0
    opponent.game_id     = game_id
    opponent.game_seat   = 1

    # Notify opponent via their lobby WebSocket
    for ws in list(_lobby_connections.get(opponent.player_id, [])):
        try:
            await ws.send_json({
                "type":          "game_started",
                "game_id":       game_id,
                "your_seat":     1,
                "opponent_name": challenger.name,
            })
        except Exception:
            pass

    await _push_lobby_update()

    return ChallengeResponse(
        game_id=game_id,
        your_seat=0,
        opponent_name=opponent.name,
        message=f"Game started against {opponent.name}. You are seat 0.",
    )


@app.delete("/lobby/leave", tags=["Lobby"])
async def leave_lobby(player_token: str = Query(...)):
    """Remove yourself from the waiting lobby."""
    player = _require_player(player_token)
    removed = _waiting_players.pop(player.player_id, None)
    if removed is None:
        raise HTTPException(status_code=400, detail="You are not in the lobby.")
    await _push_lobby_update()
    return {"message": "Left the lobby."}


# ===========================================================================
# VS-AI game — REST
# ===========================================================================

@app.post("/games/vs-ai", response_model=VsAiResponse, tags=["Game"])
async def start_vs_ai():
    """
    Start a solo game against the built-in AI opponent immediately — no
    lobby registration or opponent matching required.

    The response contains:
    - **game_id** — use this for all subsequent game endpoints
    - **player_token** — treat this like a lobby-issued token; supply it as
      `?player_token=<token>` on every game request and WebSocket connection
    - **your_seat** — always `0`; the AI occupies seat `1`

    The AI will automatically take its turns whenever it is the AI's
    move.  The normal per-turn idle timeout applies to the human player.
    """
    human  = PlayerRecord(name="Player")
    ai     = _make_ai_player()

    _players_by_token[human.token] = human

    game_id = str(uuid.uuid4())
    record  = GameRecord(game_id=game_id, player0=human, player1=ai)
    record.has_ai_opponent = True
    _games[game_id] = record

    human.game_id   = game_id
    human.game_seat = 0
    ai.game_id      = game_id
    ai.game_seat    = 1

    # If the AI moves first (game engine may assign seat 1 as the starting
    # active player), resolve those turns immediately before returning.
    await _maybe_run_ai_turn(record)

    return VsAiResponse(
        game_id=game_id,
        your_seat=0,
        player_token=human.token,
        message="Game started against the AI. You are seat 0.",
    )


# ===========================================================================
# Game — REST
# ===========================================================================

@app.get("/games/{game_id}/state", tags=["Game"])
async def get_game_state(game_id: str, player_token: str = Query(...)):
    """
    Return the current game state as seen by the requesting player.

    The response includes:
    - **my_hand** — the full private hand (card IDs + types)
    - **players[n].active** / **graveyard** — public zones for both players
    - **players[n].hand_size** — opponent's hand count
    - **players[n].revealed_hand** — any hand cards the opponent has revealed
    - **whose_turn** — `"you"` | `"opponent"` | `"game_over"`
    - **phase** — current game phase
    - **new_events** — event-log entries since the last call
    """
    player = _require_player(player_token)
    record = _require_game(game_id)
    seat   = _seat_of(record, player)
    return _public_state_for(record, seat)


@app.post("/games/{game_id}/action", response_model=ActionResponse, tags=["Game"])
async def submit_action(
    game_id: str,
    body: ActionRequest,
    player_token: str = Query(...),
):
    """
    Submit a game action.  The server derives your seat from your player_token,
    so you cannot act as the wrong player.

    **action_type** (case-insensitive) — one of:
    `PLAY_LAND`, `PASS_TURN`, `COUNTER_LAND`, `ALLOW_LAND`,
    `SPECIFY_TARGET`, `FORFEIT`

    After a successful action the server pushes a **game_state** message to
    both players' game WebSocket connections.
    """
    player = _require_player(player_token)
    record = _require_game(game_id)
    seat   = _seat_of(record, player)

    action_type = _parse_action_type(body.action_type)
    game_action = GameAction(
        action_type=action_type,
        player_id=seat,
        card_id=body.card_id,
        counter_second_card_id=body.counter_second_card_id,
        target_card_id=body.target_card_id,
    )

    result: ActionResult = record.game.apply_action(game_action)

    if result.success:
        # Reset the idle-turn clock whenever an action is accepted
        record.turn_started_at = time.monotonic()

    if result.success and record.game.phase == GamePhase.GAME_OVER:
        for p in record.players:
            p.game_id = None
            p.game_seat = None

    # Push update to WebSocket clients (non-blocking)
    asyncio.create_task(_push_game_state(record))

    # If this game has an AI, let it respond before pushing state
    if result.success:
        await _maybe_run_ai_turn(record)

    return ActionResponse(
        success=result.success,
        message=result.message,
        new_state=_public_state_for(record, seat),
    )


# ===========================================================================
# WebSocket — Lobby
# ===========================================================================

@app.websocket("/lobby/ws")
async def lobby_ws(ws: WebSocket, player_token: str = Query(...)):
    """
    **Lobby push channel.**

    Connect here after calling `/lobby/join`.  The server pushes:

    | type | when |
    |------|------|
    | `lobby_update` | whenever the waiting-player list changes |
    | `game_started` | when an opponent challenges you |

    The client may send the string `"ping"` to keep the connection alive;
    the server replies with `{"type": "pong"}`.

    Once a `game_started` message is received the client should open the
    game WebSocket at `/games/{game_id}/ws`.
    """
    player = _players_by_token.get(player_token)
    if player is None:
        await ws.close(code=4001, reason="Invalid player token")
        return

    await ws.accept()
    _lobby_connections.setdefault(player.player_id, []).append(ws)

    # Immediately send the personalised waiting list for this player
    await ws.send_json({"type": "lobby_update", "waiting": _visible_waiting(player)})

    try:
        while True:
            data = await ws.receive_text()
            if data.strip().lower() == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        lst = _lobby_connections.get(player.player_id, [])
        if ws in lst:
            lst.remove(ws)


# ===========================================================================
# WebSocket — Game
# ===========================================================================

@app.websocket("/games/{game_id}/ws")
async def game_ws(
    game_id: str,
    ws: WebSocket,
    player_token: str = Query(...),
):
    """
    **Game push channel.**

    Connect here after a game is created.  The server pushes a `game_state`
    message:
    - immediately on connect (full state snapshot)
    - after every action (to both players)

    The client may also **submit actions** over this socket instead of (or in
    addition to) the REST endpoint.  Send a JSON object with the same fields
    as the REST `ActionRequest`:

    ```json
    {
      "action_type": "PLAY_LAND",
      "card_id": "<uuid>"
    }
    ```

    The server replies with an `action_result` message (only to the sender),
    then broadcasts a `game_state` to all connected clients in the game.

    Reconnection is supported — the server keeps sending new events and
    the full state on every push.
    """
    player = _players_by_token.get(player_token)
    if player is None:
        await ws.close(code=4001, reason="Invalid player token")
        return

    record = _games.get(game_id)
    if record is None:
        await ws.close(code=4004, reason="Game not found")
        return

    seat = None
    for i, p in enumerate(record.players):
        if p.player_id == player.player_id:
            seat = i
            break
    if seat is None:
        await ws.close(code=4003, reason="You are not in this game")
        return

    await ws.accept()
    record.ws_connections[seat].append(ws)

    # Send full state immediately (handles reconnect case too)
    await ws.send_json({
        "type":  "game_state",
        "state": _public_state_for(record, seat),
    })

    try:
        while True:
            raw = await ws.receive_json()

            # Keepalive
            if raw.get("type") == "ping" or raw.get("action_type") is None:
                await ws.send_json({"type": "pong"})
                continue

            # Parse and apply action
            try:
                action_type = _parse_action_type(raw["action_type"])
            except HTTPException as e:
                await ws.send_json({"type": "error", "message": e.detail})
                continue

            game_action = GameAction(
                action_type=action_type,
                player_id=seat,
                card_id=raw.get("card_id"),
                counter_second_card_id=raw.get("counter_second_card_id"),
                target_card_id=raw.get("target_card_id"),
            )

            result: ActionResult = record.game.apply_action(game_action)

            # Acknowledge to the sender
            await ws.send_json({
                "type":    "action_result",
                "success": result.success,
                "message": result.message,
                "events":  result.events,
            })

            if result.success:
                # Reset the idle-turn clock whenever an action is accepted
                record.turn_started_at = time.monotonic()

            if result.success and record.game.phase == GamePhase.GAME_OVER:
                for p in record.players:
                    p.game_id = None
                    p.game_seat = None

            # If this game has an AI, let it respond before pushing state
            if result.success:
                await _maybe_run_ai_turn(record)

            # Broadcast updated state to both players
            await _push_game_state(record)

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            await ws.send_json({"type": "error", "message": str(exc)})
        except Exception:
            pass
    finally:
        lst = record.ws_connections.get(seat, [])
        if ws in lst:
            lst.remove(ws)


# ===========================================================================
# Health / meta
# ===========================================================================

@app.get("/health", tags=["Meta"])
async def health():
    """Server health check and quick stats."""
    return {
        "status":          "ok",
        "waiting_players": len(_waiting_players),
        "active_games":    len(_games),
    }


# ===========================================================================
# Static files
# ===========================================================================

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", tags=["Meta"])
async def serve_index():
    """Serve the game frontend."""
    index_path = os.path.join("static", "index.html")
    return FileResponse(index_path)


# ===========================================================================
# Entry point
# ===========================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)
