#!/usr/bin/env bash
set -e

gcloud builds submit --tag gcr.io/basic-land-game/game-server

gcloud beta run deploy game-server \
  --image gcr.io/basic-land-game/game-server \
  --platform managed \
  --region us-central1 \
  --domain basic-land-game.robopenguins.com \
  --allow-unauthenticated \
  --port 8000 \
  --max-instances 1     # Never scale beyond 1 since state is in memory
