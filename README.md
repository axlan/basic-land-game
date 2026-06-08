
```
PLAY_OR_PASS
  ├─ PASS_TURN → advance turn (draw for next player)
  └─ PLAY_LAND → AWAIT_COUNTER
                    ├─ COUNTER_LAND → land → graveyard, advance turn
                    └─ ALLOW_LAND
                          ├─ Island: draw immediately, advance turn
                          ├─ Mountain/Forest/Swamp with valid targets → RESOLVE_EFFECT
                          │     └─ target action → advance turn
                          └─ Plains → RESOLVE_EFFECT (PLAINS_TARGET)
                                └─ if copying Island: draw, advance turn
                                └─ if copying Mountain/Forest/Swamp: re-enter RESOLVE_EFFECT
                                      └─ target action → advance turn
```

`uvicorn server:app --reload --port 8000`

TODO:
Make responsive
Password for match making
Have tests use public API.
