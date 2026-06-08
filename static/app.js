/**
 * Basic Land Game — Client-Side Application
 * Handles API calls, WebSockets, Phaser rendering, and game state automation.
 */

// ==========================================
// Globals & State
// ==========================================
let playerToken = localStorage.getItem('basic_land_player_token');
let playerId = localStorage.getItem('basic_land_player_id');
let playerName = localStorage.getItem('basic_land_player_name');
let gameId = localStorage.getItem('basic_land_game_id');
let counterStrategy = localStorage.getItem('basic_land_counter_strategy') || 'always_prompt';

let gameState = null;
let selectedCardsInHand = []; // Card IDs selected in hand (up to 2 for counters)
let selectedTargetCard = null; // Card ID selected for target effects

// ==========================================
// Card Tooltip Data
// ==========================================
const CARD_TOOLTIP_DATA = {
  forest:   { emoji: '🌳', name: 'Forest',   body: 'Return any land from <strong>your graveyard</strong> to your hand.' },
  island:   { emoji: '💧', name: 'Island',   body: 'Draw a card. <strong>Or</strong> discard Island + another land to <strong>counter</strong> an opponent\'s land play.' },
  mountain: { emoji: '🔥', name: 'Mountain', body: '<strong>Destroy</strong> one of your opponent\'s active lands. Target is declared before they can counter.' },
  plains:   { emoji: '☀️', name: 'Plains',   body: '<strong>Copy</strong> the effect of one of your other non-Plains active lands.' },
  swamp:    { emoji: '💀', name: 'Swamp',    body: 'Look at the opponent\'s hand and choose a card for them to <strong>discard</strong>.' },
};

// Inject and manage the floating tooltip element
const _tooltip = (() => {
  const el = document.createElement('div');
  el.id = 'card-tooltip';
  el.innerHTML = `<div class="tooltip-inner">
    <div class="tooltip-header">
      <span class="tooltip-emoji"></span>
      <span class="tooltip-name"></span>
    </div>
    <div class="tooltip-body"></div>
  </div>`;
  document.body.appendChild(el);

  return {
    show(landType, canvasX, canvasY) {
      const data = CARD_TOOLTIP_DATA[landType];
      if (!data) return;

      el.querySelector('.tooltip-emoji').textContent = data.emoji;
      el.querySelector('.tooltip-name').textContent = data.name;
      el.querySelector('.tooltip-body').innerHTML = data.body;
      el.setAttribute('data-land', landType);

      const canvas = document.querySelector('#game-canvas-container canvas');
      if (!canvas) return;
      const rect = canvas.getBoundingClientRect();

      // Scale factor: rendered canvas size vs. Phaser's logical resolution
      const scaleX = rect.width  / 960;
      const scaleY = rect.height / 700;

      const tipW = 200;
      let left = rect.left + canvasX * scaleX - tipW / 2;
      let top  = rect.top  + canvasY * scaleY - 85;

      // Keep inside viewport
      left = Math.max(8, Math.min(left, window.innerWidth  - tipW - 8));
      top  = Math.max(8, Math.min(top,  window.innerHeight - 120  - 8));

      el.style.left = left + 'px';
      el.style.top  = top  + 'px';
      el.classList.add('visible');
    },
    hide() {
      el.classList.remove('visible');
    }
  };
})();

let lobbyWs = null;
let gameWs = null;
let lobbyPingInterval = null;
let gamePingInterval = null;

// Phaser objects
let phaserGame = null;
let gameScene = null;

// ==========================================
// Card UI class (Phaser Container)
// ==========================================
class CardUI extends Phaser.GameObjects.Container {
  constructor(scene, x, y, landType, cardId, isFaceUp, isSelected, isTargetable) {
    super(scene, x, y);
    this.landType = landType;
    this.cardId = cardId;
    this.isFaceUp = isFaceUp;
    this.isSelected = isSelected;
    this.isTargetable = isTargetable;

    let textureKey = 'card_back';
    if (isFaceUp && landType) {
      textureKey = 'card_' + landType;
    }

    // 1. Selection / Target Highlight Glow (Drawn as background)
    let glowSize = 0;
    let glowColor = 0xffffff;
    if (isSelected) {
      glowSize = 6;
      glowColor = 0x818cf8; // indigo glow
    } else if (isTargetable) {
      glowSize = 6;
      glowColor = 0xfbbf24; // yellow glow for targets
    }

    if (glowSize > 0) {
      const glow = scene.add.graphics();
      glow.lineStyle(glowSize, glowColor, 0.85);
      glow.strokeRoundedRect(-45 - glowSize/2, -65 - glowSize/2, 90 + glowSize, 130 + glowSize, 10);
      this.add(glow);

      if (isTargetable) {
        // Pulsing animation for targetable lands
        scene.tweens.add({
          targets: glow,
          alpha: 0.35,
          duration: 900,
          yoyo: true,
          repeat: -1
        });
      }
    }

    // 2. Base Card Sprite
    const sprite = scene.add.sprite(0, 0, textureKey);
    this.add(sprite);

    // 3. Card face elements
    if (isFaceUp && landType) {
      const emojis = {
        forest: '🌳',
        island: '💧',
        mountain: '🔥',
        plains: '☀️',
        swamp: '💀'
      };

      const nameColors = {
        forest: '#a7f3d0',
        island: '#bfdbfe',
        mountain: '#fecaca',
        plains: '#fef08a',
        swamp: '#e9d5ff'
      };

      // Large central emoji
      const emojiText = scene.add.text(0, -18, emojis[landType] || '🃏', {
        fontSize: '32px',
        fontFamily: 'Outfit, Arial'
      }).setOrigin(0.5);
      this.add(emojiText);

      // Card land type name
      const typeText = scene.add.text(0, 18, landType.toUpperCase(), {
        fontSize: '11px',
        fontFamily: 'Outfit, sans-serif',
        fontWeight: '700',
        fill: nameColors[landType] || '#ffffff'
      }).setOrigin(0.5);
      this.add(typeText);

      // Shortened Card ID
      const shortId = cardId.substring(0, 8);
      const idText = scene.add.text(0, 42, shortId, {
        fontSize: '8px',
        fontFamily: 'monospace',
        fill: '#64748b'
      }).setOrigin(0.5);
      this.add(idText);
    } else {
      // Facedown card details
      const centerSymbol = scene.add.text(0, 0, '✦', {
        fontSize: '24px',
        fontFamily: 'Outfit, Arial',
        fill: '#fbbf24'
      }).setOrigin(0.5);
      this.add(centerSymbol);
    }

    // Interactive config
    this.setSize(90, 130);
    this.setInteractive({ useHandCursor: true });

    // Click handler
    this.on('pointerdown', () => {
      scene.events.emit('cardClicked', this);
    });

    // Hover effects (lift and grow, pop depth)
    this.on('pointerover', () => {
      this._originalDepth = this.depth;
      this.setDepth(1000);
      scene.tweens.add({
        targets: this,
        y: y - 12,
        scale: 1.05,
        duration: 150
      });
      // Show tooltip only for face-up hand cards
      if (isFaceUp && landType) {
        _tooltip.show(landType, x, y - 65);
      }
    });

    this.on('pointerout', () => {
      this.setDepth(this._originalDepth !== undefined ? this._originalDepth : 0);
      scene.tweens.add({
        targets: this,
        y: y,
        scale: 1.0,
        duration: 150
      });
      _tooltip.hide();
    });

    scene.add.existing(this);
  }
}

// ==========================================
// Phaser Scene Definition
// ==========================================
class BasicLandGameScene extends Phaser.Scene {
  constructor() {
    super('BasicLandGameScene');
  }

  preload() {
    // Generate card textures dynamically to ensure instant load and zero dependencies
    this.createCardTexture('card_forest', 0x14532d); // Dark Green
    this.createCardTexture('card_island', 0x1e3a8a); // Dark Blue
    this.createCardTexture('card_mountain', 0x7f1d1d); // Dark Red
    this.createCardTexture('card_plains', 0x713f12); // Gold / Dark Yellow
    this.createCardTexture('card_swamp', 0x3b0764); // Dark Purple
    this.createCardBackTexture('card_back', 0x0f172a); // Slate-900 with Amber highlights
  }

  create() {
    gameScene = this;
    this.cardsGroup = this.add.group();

    // Setup visual dividers
    const gridGraphics = this.add.graphics();
    gridGraphics.lineStyle(1, 0x334155, 0.25);
    // Draw divider between Opponent and Player boards
    gridGraphics.lineBetween(50, 350, 930, 350);
    
    // Handle card click events in the scene
    this.events.on('cardClicked', (cardUI) => {
      handleCardUIInteraction(cardUI);
    });

    if (gameState) {
      this.drawBoard();
    }
  }

  // Render a player's active zone as grouped stacks, one per land type.
  // centreX is the horizontal midpoint of the zone, zoneWidth is the
  // total horizontal space available, baseY is the vertical centre of a card.
  drawActiveZone(cards, baseY, targetableIds) {
    if (!cards || cards.length === 0) return;

    // Group by land type, preserving insertion order
    const groups = {};
    const ORDER = ['forest', 'island', 'mountain', 'plains', 'swamp'];
    ORDER.forEach(t => { groups[t] = []; });
    cards.forEach(c => {
      if (!groups[c.land_type]) groups[c.land_type] = [];
      groups[c.land_type].push(c);
    });

    // Keep only types that actually appear
    const types = ORDER.filter(t => groups[t].length > 0);
    const numStacks = types.length;

    // Horizontal positions for each stack (same helper used elsewhere)
    const stackX = getCardXCoordinates(490, 600, numStacks, 90);

    types.forEach((type, stackIdx) => {
      const stack = groups[type];
      const cx = stackX[stackIdx];

      // Vertical offset per card within the stack (peek effect)
      const peekStep = 10;  // px between successive cards
      const stackTop = baseY - (stack.length - 1) * peekStep / 2;

      stack.forEach((c, cardIdx) => {
        const isTargetable = targetableIds.has(c.card_id);
        const yPos = stackTop + cardIdx * peekStep;
        const card = new CardUI(this, cx, yPos, c.land_type, c.card_id, true, false, isTargetable);
        card.setDepth(cardIdx);
        this.cardsGroup.add(card);
      });

      // Count badge — only shown when stack has more than 1 card
      if (stack.length > 1) {
        const badgeBg = this.add.graphics();
        badgeBg.fillStyle(0x1e1b4b, 0.92);
        badgeBg.lineStyle(1.5, 0x818cf8, 0.85);
        badgeBg.fillRoundedRect(cx + 28, baseY - 54, 22, 22, 6);
        badgeBg.strokeRoundedRect(cx + 28, baseY - 54, 22, 22, 6);
        badgeBg.setDepth(1001);
        this.cardsGroup.add(badgeBg);

        const badge = this.add.text(cx + 39, baseY - 43, `${stack.length}`, {
          fontSize: '12px',
          fontFamily: 'Outfit, sans-serif',
          fontStyle: 'bold',
          fill: '#a5b4fc'
        }).setOrigin(0.5);
        badge.setDepth(1002);
        this.cardsGroup.add(badge);
      }
    });
  }

  createCardTexture(key, colorHex) {
    const w = 90;
    const h = 130;
    const r = 8;
    const g = this.make.graphics({ x: 0, y: 0, add: false });

    // Background
    g.fillStyle(colorHex, 0.95);
    g.fillRoundedRect(0, 0, w, h, r);

    // Border
    g.lineStyle(2, 0xffffff, 0.2);
    g.strokeRoundedRect(0, 0, w, h, r);

    // Inner frame
    g.lineStyle(1, 0xffffff, 0.08);
    g.strokeRoundedRect(5, 5, w - 10, h - 10, r - 2);

    g.generateTexture(key, w, h);
    g.destroy();
  }

  createCardBackTexture(key, colorHex) {
    const w = 90;
    const h = 130;
    const r = 8;
    const g = this.make.graphics({ x: 0, y: 0, add: false });

    // Background
    g.fillStyle(colorHex, 0.95);
    g.fillRoundedRect(0, 0, w, h, r);

    // Border (Golden accent)
    g.lineStyle(2.5, 0xd97706, 0.85); // Amber-600
    g.strokeRoundedRect(0, 0, w, h, r);

    // Inner outline
    g.lineStyle(1.5, 0xd97706, 0.35);
    g.strokeRoundedRect(6, 6, w - 12, h - 12, r - 2);

    // Cross lines
    g.lineStyle(1, 0xd97706, 0.15);
    g.moveTo(12, 18);
    g.lineTo(w - 12, h - 18);
    g.moveTo(w - 12, 18);
    g.lineTo(12, h - 18);

    g.generateTexture(key, w, h);
    g.destroy();
  }

  drawBoard() {
    this.cardsGroup.clear(true, true);
    if (!gameState) return;

    const seat = gameState.my_seat;
    const oppSeat = 1 - seat;

    const myData = gameState.players[seat];
    const oppData = gameState.players[oppSeat];

    // Determine targetable card IDs for current phase
    const targetableIds = getTargetableCardIds();

    // ----------------------------------------------------
    // OPPONENT SIDE (Top)
    // ----------------------------------------------------
    
    // Opponent Library
    const oppLibSize = oppData.library_size;
    const oppLibCard = new CardUI(this, 100, 130, null, 'opp_lib', false, false, false);
    this.cardsGroup.add(oppLibCard);
    const oppLibText = this.add.text(100, 205, `Library: ${oppLibSize}`, {
      fontSize: '11px',
      fontFamily: 'Outfit, sans-serif',
      fill: '#94a3b8'
    }).setOrigin(0.5);
    this.cardsGroup.add(oppLibText);

    // Opponent Hand
    const oppHandSize = oppData.hand_size;
    const revealedOppHand = oppData.revealed_hand || [];
    const oppHandX = getCardXCoordinates(490, 500, oppHandSize, 90);
    for (let i = 0; i < oppHandSize; i++) {
      // Some cards might be revealed due to Swamp discard resolution
      const revCard = revealedOppHand[i];
      let isFaceUp = false;
      let landType = null;
      let cardId = `opp_hand_${i}`;

      if (revCard) {
        isFaceUp = true;
        landType = revCard.land_type;
        cardId = revCard.card_id;
      }

      const isTargetable = targetableIds.has(cardId);
      const oppCard = new CardUI(this, oppHandX[i], 100, landType, cardId, isFaceUp, false, isTargetable);
      this.cardsGroup.add(oppCard);
    }

    // Opponent Active lands
    const oppActive = oppData.active || [];
    this.drawActiveZone(oppActive, 240, targetableIds);

    // Opponent Graveyard
    const oppGY = oppData.graveyard || [];
    if (oppGY.length > 0) {
      const maxSpacing = 15;
      const maxTotalHeight = 120;
      const spacing = oppGY.length > 1 ? Math.min(maxSpacing, maxTotalHeight / (oppGY.length - 1)) : 0;

      oppGY.forEach((c, idx) => {
        const isTargetable = targetableIds.has(c.card_id);
        const yPos = 130 + idx * spacing;
        const card = new CardUI(this, 880, yPos, c.land_type, c.card_id, true, false, isTargetable);
        card.setDepth(idx);
        this.cardsGroup.add(card);
      });

      const labelY = 130 + (oppGY.length - 1) * spacing + 75;
      const oppGYText = this.add.text(880, labelY, `Graveyard: ${oppGY.length}`, {
        fontSize: '11px',
        fontFamily: 'Outfit, sans-serif',
        fill: '#94a3b8'
      }).setOrigin(0.5);
      this.cardsGroup.add(oppGYText);
    } else {
      const emptyGY = this.add.graphics();
      emptyGY.lineStyle(1.5, 0x334155, 0.4);
      emptyGY.strokeRoundedRect(880 - 45, 130 - 65, 90, 130, 8);
      const oppEmptyText = this.add.text(880, 130, 'Empty GY', {
        fontSize: '10px',
        fontFamily: 'Outfit, sans-serif',
        fill: '#475569'
      }).setOrigin(0.5);
      this.cardsGroup.add(oppEmptyText);
      this.cardsGroup.add(emptyGY);
    }

    // ----------------------------------------------------
    // PLAYER SIDE (Bottom)
    // ----------------------------------------------------
    
    // Player Library
    const myLibSize = myData.library_size;
    const myLibCard = new CardUI(this, 100, 570, null, 'my_lib', false, false, false);
    this.cardsGroup.add(myLibCard);
    const myLibText = this.add.text(100, 645, `Library: ${myLibSize}`, {
      fontSize: '11px',
      fontFamily: 'Outfit, sans-serif',
      fill: '#94a3b8'
    }).setOrigin(0.5);
    this.cardsGroup.add(myLibText);

    // Player Active lands
    const myActive = myData.active || [];
    this.drawActiveZone(myActive, 460, targetableIds);

    // Player Hand
    const myHand = gameState.my_hand || [];
    const myHandX = getCardXCoordinates(490, 650, myHand.length, 90);
    myHand.forEach((c, idx) => {
      const isSelected = selectedCardsInHand.includes(c.card_id);
      const isTargetable = targetableIds.has(c.card_id);
      const yOffset = isSelected ? 580 : 600;

      const card = new CardUI(this, myHandX[idx], yOffset, c.land_type, c.card_id, true, isSelected, isTargetable);
      this.cardsGroup.add(card);
    });

    // Player Graveyard
    const myGY = myData.graveyard || [];
    // Spread graveyard cards to 50% overlap when they are Forest targets
    const isForestTargeting = gameState.phase === 'RESOLVE_EFFECT' &&
      parsePendingPlay(gameState.pending_play)?.land_type === 'forest';
    const myGYSpacing = isForestTargeting ? 65 : 15; // 65px = 50% of card height (130px)

    if (myGY.length > 0) {
      const maxTotalHeight = isForestTargeting
        ? myGY.length * myGYSpacing          // allow full spread, no cap
        : 120;                                // original compact cap
      const spacing = myGY.length > 1
        ? Math.min(myGYSpacing, maxTotalHeight / (myGY.length - 1))
        : 0;

      myGY.forEach((c, idx) => {
        const isTargetable = targetableIds.has(c.card_id);
        const yPos = 570 - idx * spacing;
        const card = new CardUI(this, 880, yPos, c.land_type, c.card_id, true, false, isTargetable);
        card.setDepth(idx);
        this.cardsGroup.add(card);
      });

      const labelY = 570 + 75;
      const myGYText = this.add.text(880, labelY, `Graveyard: ${myGY.length}`, {
        fontSize: '11px',
        fontFamily: 'Outfit, sans-serif',
        fill: '#94a3b8'
      }).setOrigin(0.5);
      this.cardsGroup.add(myGYText);
    } else {
      const emptyGY = this.add.graphics();
      emptyGY.lineStyle(1.5, 0x334155, 0.4);
      emptyGY.strokeRoundedRect(880 - 45, 570 - 65, 90, 130, 8);
      const myEmptyText = this.add.text(880, 570, 'Empty GY', {
        fontSize: '10px',
        fontFamily: 'Outfit, sans-serif',
        fill: '#475569'
      }).setOrigin(0.5);
      this.cardsGroup.add(myEmptyText);
      this.cardsGroup.add(emptyGY);
    }

    // ----------------------------------------------------
    // BATTLEGROUND (Middle - Pending Play)
    // ----------------------------------------------------
    const pending = parsePendingPlay(gameState.pending_play);
    if (pending) {
      const card = new CardUI(this, 490, 350, pending.land_type, pending.card_id, true, false, false);
      this.cardsGroup.add(card);

      const glow = this.add.graphics();
      glow.lineStyle(4, 0xfbbf24, 0.7);
      glow.strokeRoundedRect(490 - 47, 350 - 67, 94, 134, 10);
      this.cardsGroup.add(glow);

      this.tweens.add({
        targets: glow,
        alpha: 0.25,
        duration: 700,
        yoyo: true,
        repeat: -1
      });

      const label = (gameState.phase === 'AWAIT_COUNTER') ? 'PENDING LAND PLAY' : 'RESOLVING EFFECT';
      const labelText = this.add.text(490, 272, label, {
        fontSize: '11px',
        fontFamily: 'Outfit, sans-serif',
        fontWeight: '700',
        fill: '#fbbf24',
        backgroundColor: 'rgba(15, 23, 42, 0.85)',
        padding: { x: 8, y: 4 }
      }).setOrigin(0.5);
      this.cardsGroup.add(labelText);
    }
  }
}

function updateOrientationUI() {
  const overlay = document.getElementById('orientation-overlay');
  // Use screen.orientation if available (more reliable than innerWidth/innerHeight
  // which can be stale during orientation transitions on some mobile browsers)
  const isPortrait = window.screen?.orientation
    ? window.screen.orientation.type.startsWith('portrait')
    : window.innerHeight > window.innerWidth;

  overlay.style.display = isPortrait ? 'flex' : 'none';
}

// ==========================================
// API Helpers
// ==========================================
async function apiCall(endpoint, method = 'GET', body = null) {
  const url = new URL(endpoint, window.location.origin);
  if (playerToken) {
    url.searchParams.set('player_token', playerToken);
  }

  const options = {
    method,
    headers: {
      'Content-Type': 'application/json'
    }
  };

  if (body) {
    options.body = JSON.stringify(body);
  }

  const response = await fetch(url, options);
  if (!response.ok) {
    const errData = await response.json().catch(() => ({}));
    const err = new Error(errData.detail || `HTTP Error ${response.status}`);
    err.status = response.status;
    throw err;
  }
  return response.json();
}

// ==========================================
// Lobby Matchmaking Operations
// ==========================================
async function joinLobby() {
  const usernameInput = document.getElementById('username-input');
  const name = usernameInput.value.trim();
  if (!name) {
    showToast('Name must not be empty!', 'error');
    return;
  }

  const reservedForInput = document.getElementById('reserved-for-input');
  const reservedForName = reservedForInput ? reservedForInput.value.trim() || null : null;

  try {
    const body = { name };
    if (reservedForName) body.reserved_for_name = reservedForName;

    const data = await apiCall('/lobby/join', 'POST', body);
    playerToken = data.player_token;
    playerId = data.player_id;
    playerName = data.name;

    localStorage.setItem('basic_land_player_token', playerToken);
    localStorage.setItem('basic_land_player_id', playerId);
    localStorage.setItem('basic_land_player_name', playerName);
    if (reservedForName) {
      localStorage.setItem('basic_land_reserved_for', reservedForName);
    } else {
      localStorage.removeItem('basic_land_reserved_for');
    }

    showToast(`Registered successfully as ${playerName}!`, 'success');
    
    // Transition UI
    document.getElementById('join-form').style.display = 'none';
    document.getElementById('lobby-panel').style.display = 'block';
    document.getElementById('player-profile-name').textContent = playerName;

    // Show reservation banner if a specific opponent was requested
    const banner = document.getElementById('reservation-banner');
    if (reservedForName && banner) {
      document.getElementById('reservation-target-name').textContent = reservedForName;
      banner.style.display = 'flex';
    }

    // Connect to Lobby WS and fetch waiting list
    initLobbyWs();
    refreshLobby();
  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function refreshLobby() {
  if (!playerToken) return;
  try {
    const data = await apiCall('/lobby/waiting');
    updateWaitingList(data.waiting);
  } catch (err) {
    showToast('Failed to refresh lobby list', 'error');
  }
}

async function challengePlayer(opponentId) {
  try {
    showToast('Sending challenge...', 'success');
    const data = await apiCall('/lobby/challenge', 'POST', { opponent_player_id: opponentId });
    // Challenger is always seat 0
    startGameSession(data.game_id, 0, data.opponent_name);
  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function leaveLobby() {
  try {
    await apiCall('/lobby/leave', 'DELETE');
    localStorage.clear();
    playerToken = null;
    playerId = null;
    playerName = null;
    gameId = null;

    // Hide reservation banner
    const banner = document.getElementById('reservation-banner');
    if (banner) banner.style.display = 'none';

    if (lobbyWs) {
      lobbyWs.close();
      lobbyWs = null;
    }
    stopLobbyPing();

    document.getElementById('join-form').style.display = 'block';
    document.getElementById('lobby-panel').style.display = 'none';
    showToast('Left the lobby.', 'success');
  } catch (err) {
    showToast(err.message, 'error');
  }
}

function updateWaitingList(waiting) {
  const list = document.getElementById('waiting-players-list');
  list.innerHTML = '';

  // Filter out self
  const opponents = waiting.filter(p => p.player_id !== playerId);

  if (opponents.length === 0) {
    list.innerHTML = '<li class="empty-lobby">No other players are currently waiting.</li>';
    return;
  }

  opponents.forEach(p => {
    const li = document.createElement('li');
    li.className = 'waiting-item';

    const nameSpan = document.createElement('span');
    nameSpan.className = 'waiting-name';
    nameSpan.textContent = p.name;

    // Show a lock badge if this slot was reserved specifically for us
    if (p.reserved_for_name) {
      const badge = document.createElement('span');
      badge.className = 'reserved-badge';
      badge.title = `This player is waiting only for you`;
      badge.textContent = '🔒 Private';
      nameSpan.appendChild(badge);
    }

    li.appendChild(nameSpan);

    const chalBtn = document.createElement('button');
    chalBtn.className = 'btn-secondary';
    chalBtn.textContent = 'Challenge';
    chalBtn.onclick = () => challengePlayer(p.player_id);
    li.appendChild(chalBtn);

    list.appendChild(li);
  });
}

// ==========================================
// WebSocket Connections
// ==========================================
function initLobbyWs() {
  if (lobbyWs) {
    lobbyWs.close();
  }

  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const url = `${protocol}//${window.location.host}/lobby/ws?player_token=${playerToken}`;
  lobbyWs = new WebSocket(url);

  lobbyWs.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      if (msg.type === 'lobby_update') {
        updateWaitingList(msg.waiting);
      } else if (msg.type === 'game_started') {
        showToast(`Challenge accepted! Game started.`, 'success');
        startGameSession(msg.game_id, msg.your_seat, msg.opponent_name);
      }
    } catch (e) {
      console.error('Lobby WS error parsing message:', e);
    }
  };

  lobbyWs.onopen = () => {
    startLobbyPing();
  };

  lobbyWs.onclose = () => {
    stopLobbyPing();
  };
}

function startLobbyPing() {
  stopLobbyPing();
  lobbyPingInterval = setInterval(() => {
    if (lobbyWs && lobbyWs.readyState === WebSocket.OPEN) {
      lobbyWs.send('ping');
    }
  }, 20000);
}

function stopLobbyPing() {
  if (lobbyPingInterval) {
    clearInterval(lobbyPingInterval);
    lobbyPingInterval = null;
  }
}

function initGameWs() {
  if (gameWs) {
    gameWs.close();
  }

  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const url = `${protocol}//${window.location.host}/games/${gameId}/ws?player_token=${playerToken}`;
  gameWs = new WebSocket(url);

  gameWs.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      if (msg.type === 'game_state') {
        onGameStateUpdate(msg.state);
      } else if (msg.type === 'action_result') {
        if (!msg.success) {
          showToast(msg.message, 'error');
        } else {
          showToast(msg.message || 'Action successful!', 'success');
        }
      } else if (msg.type === 'error') {
        showToast(msg.message, 'error');
      }
    } catch (e) {
      console.error('Game WS error parsing message:', e);
    }
  };

  gameWs.onopen = () => {
    startGamePing();
  };

  gameWs.onclose = () => {
    stopGamePing();
  };
}

function startGamePing() {
  stopGamePing();
  gamePingInterval = setInterval(() => {
    if (gameWs && gameWs.readyState === WebSocket.OPEN) {
      gameWs.send(JSON.stringify({ type: 'ping' }));
    }
  }, 20000);
}

function stopGamePing() {
  if (gamePingInterval) {
    clearInterval(gamePingInterval);
    gamePingInterval = null;
  }
}

// ==========================================
// In-game Flow & Controls
// ==========================================
function startGameSession(gId, seat, oppName) {
  gameId = gId;
  localStorage.setItem('basic_land_game_id', gameId);

  // Close Lobby WS since we are entering game
  if (lobbyWs) {
    lobbyWs.close();
    lobbyWs = null;
  }
  stopLobbyPing();

  // Transition UI screens
  document.getElementById('lobby-screen').classList.add('hidden');
  document.getElementById('game-screen').classList.remove('hidden');

  document.getElementById('opponent-name-indicator').textContent = oppName;
  document.getElementById('seat-indicator').textContent = seat;

  // Clear Event Journal UI and card selections
  document.getElementById('event-log-list').innerHTML = '<li class="log-entry log-turn">Connected to game room.</li>';
  selectedCardsInHand = [];
  selectedTargetCard = null;

  // Init Phaser Game canvas if not already created
  if (!phaserGame) {
    initPhaserGame();
  }

  // Setup WS connection
  initGameWs();
}

function onGameStateUpdate(state) {
  gameState = state;

  // Render text updates
  document.getElementById('phase-indicator').textContent = state.phase.replace(/_/g, ' ');
  document.getElementById('turn-indicator').textContent = state.turn_number;

  // Whose turn visual banner
  const banner = document.getElementById('turn-banner');
  if (state.whose_turn === 'you') {
    banner.textContent = 'YOUR ACTION';
    banner.className = 'turn-mine';
  } else if (state.whose_turn === 'opponent') {
    banner.textContent = "OPPONENT'S ACTION";
    banner.className = 'turn-opp';
  } else {
    banner.textContent = 'GAME OVER';
    banner.className = 'turn-over';

    // Show the game-over overlay (deduplicated — only once per game)
    if (!document.getElementById('game-over-overlay').dataset.shown) {
      document.getElementById('game-over-overlay').dataset.shown = '1';
      showGameOverOverlay(state);
    }
  }

  // Append new event log items
  if (state.new_events && state.new_events.length > 0) {
    appendEvents(state.new_events);
  }

  // Auto-pass / auto-counter resolution logic
  handleCounterAutoRun();

  // Update button enabled states
  updateControls();

  // Request Phaser Scene redraw
  if (gameScene) {
    gameScene.drawBoard();
  }
}

function sendGameAction(actionType, extraParams = {}) {
  if (!gameWs || gameWs.readyState !== WebSocket.OPEN) {
    showToast('Game connection is closed.', 'error');
    return;
  }

  const payload = {
    action_type: actionType,
    ...extraParams
  };

  gameWs.send(JSON.stringify(payload));
}

// Logic for card clicks in Phaser Scene
function handleCardUIInteraction(cardUI) {
  if (!gameState || gameState.whose_turn !== 'you') {
    showToast('Not your turn to act!', 'error');
    return;
  }

  const seat = gameState.my_seat;
  const myData = gameState.players[seat];
  const oppSeat = 1 - seat;
  const oppData = gameState.players[oppSeat];

  // 1. PLAY OR PASS PHASE
  if (gameState.phase === 'PLAY_OR_PASS') {
    // We can only select cards in our own hand to play
    const inHand = myData.hand_card || (() => {
      return gameState.my_hand.some(c => c.card_id === cardUI.cardId);
    })();
    
    if (inHand) {
      if (selectedCardsInHand.includes(cardUI.cardId)) {
        selectedCardsInHand = [];
      } else {
        selectedCardsInHand = [cardUI.cardId];
      }
      if (gameScene) gameScene.drawBoard();
      updateControls();
    }
  }

  // 2. AWAIT COUNTER PHASE
  else if (gameState.phase === 'AWAIT_COUNTER') {
    // Non-active player is selecting counter spell cost (Island + 1 other card in hand)
    const inHand = gameState.my_hand.some(c => c.card_id === cardUI.cardId);
    if (inHand) {
      if (selectedCardsInHand.includes(cardUI.cardId)) {
        selectedCardsInHand = selectedCardsInHand.filter(id => id !== cardUI.cardId);
      } else {
        selectedCardsInHand.push(cardUI.cardId);
        if (selectedCardsInHand.length > 2) {
          selectedCardsInHand.shift(); // keep max 2
        }
      }
      if (gameScene) gameScene.drawBoard();
      updateControls();
    }
  }

  // 3. RESOLVE EFFECT PHASE
  else if (gameState.phase === 'RESOLVE_EFFECT') {
    const targetableIds = getTargetableCardIds();
    if (targetableIds.has(cardUI.cardId)) {
      // Valid target selected! Immediately submit the targeted action.
      const pending = parsePendingPlay(gameState.pending_play);
      if (!pending) return;

      const landType = pending.land_type;
      let actionType = '';

      if (landType === 'plains') actionType = 'PLAINS_TARGET';
      else if (landType === 'mountain') actionType = 'MOUNTAIN_TARGET';
      else if (landType === 'forest') actionType = 'FOREST_TARGET';
      else if (landType === 'swamp') actionType = 'SWAMP_DISCARD';

      if (actionType) {
        sendGameAction(actionType, { target_card_id: cardUI.cardId });
        selectedCardsInHand = [];
        selectedTargetCard = null;
      }
    }
  }
}

// Determine highlighted cards based on current phase and target logic
function getTargetableCardIds() {
  const ids = new Set();
  if (!gameState || gameState.whose_turn !== 'you') return ids;

  const seat = gameState.my_seat;
  const oppSeat = 1 - seat;

  const myData = gameState.players[seat];
  const oppData = gameState.players[oppSeat];

  // Under PLAY_OR_PASS, highlight hand cards that can be played
  if (gameState.phase === 'PLAY_OR_PASS') {
    gameState.my_hand.forEach(c => ids.add(c.card_id));
  }

  // Under AWAIT_COUNTER, highlight hand cards (for selecting Island + other)
  else if (gameState.phase === 'AWAIT_COUNTER') {
    gameState.my_hand.forEach(c => ids.add(c.card_id));
  }

  // Under RESOLVE_EFFECT, highlight depending on land type
  else if (gameState.phase === 'RESOLVE_EFFECT') {
    const pending = parsePendingPlay(gameState.pending_play);
    if (pending) {
      const type = pending.land_type;

      if (type === 'mountain') {
        // Targets: opponent active lands
        const oppActive = oppData.active || [];
        oppActive.forEach(c => ids.add(c.card_id));
      } 
      else if (type === 'forest') {
        // Targets: own graveyard lands
        const myGY = myData.graveyard || [];
        myGY.forEach(c => ids.add(c.card_id));
      } 
      else if (type === 'swamp') {
        // Targets: opponent hand cards (fully visible/revealed in Swamp phase)
        const revealedOpp = oppData.revealed_hand || [];
        revealedOpp.forEach(c => ids.add(c.card_id));
      } 
      else if (type === 'plains') {
        // Targets: own active lands, except Plains and except the pending card itself
        const myActive = myData.active || [];
        myActive.forEach(c => {
          if (c.land_type !== 'plains' && c.card_id !== pending.card_id) {
            ids.add(c.card_id);
          }
        });
      }
    }
  }

  return ids;
}

// Strategy automated runs for counters
function handleCounterAutoRun() {
  if (!gameState) return;
  if (gameState.phase !== 'AWAIT_COUNTER') return;
  if (gameState.whose_turn !== 'you') return;

  const strategy = getSelectedCounterStrategy();

  if (strategy === 'always_pass') {
    showToast('Auto-passing counter spell window...', 'success');
    sendGameAction('ALLOW_LAND');
  } 
  else if (strategy === 'smart_prompt') {
    const hand = gameState.my_hand || [];
    const hasIsland = hand.some(c => c.land_type === 'island');
    const hasAdditional = hand.length >= 2;

    if (!(hasIsland && hasAdditional)) {
      showToast('Smart pass: No counter spell option in hand', 'success');
      sendGameAction('ALLOW_LAND');
    } else {
      showToast('Holding Counter spell options! Action required.', 'success');
    }
  }
}

// Update enabled/disabled status of buttons in the sidebar
function updateControls() {
  const btnPlay = document.getElementById('btn-play-land');
  const btnPass = document.getElementById('btn-pass-turn');
  const btnCounter = document.getElementById('btn-counter-play');
  const btnAllow = document.getElementById('btn-allow-play');
  const btnReset = document.getElementById('btn-reset-selection');

  // Disable all by default
  btnPlay.disabled = true;
  btnPass.disabled = true;
  btnCounter.disabled = true;
  btnAllow.disabled = true;
  btnReset.disabled = true;

  if (!gameState || gameState.whose_turn !== 'you') {
    return;
  }

  // PLAY OR PASS PHASE
  if (gameState.phase === 'PLAY_OR_PASS') {
    btnPass.disabled = false;
    btnReset.disabled = (selectedCardsInHand.length === 0);

    if (selectedCardsInHand.length === 1) {
      btnPlay.disabled = false;
    }
  }

  // AWAIT COUNTER PHASE
  else if (gameState.phase === 'AWAIT_COUNTER') {
    btnAllow.disabled = false;
    btnReset.disabled = (selectedCardsInHand.length === 0);

    // Verify counter conditions: 2 cards, one is Island
    if (selectedCardsInHand.length === 2) {
      const myHand = gameState.my_hand || [];
      const selCardsObj = myHand.filter(c => selectedCardsInHand.includes(c.card_id));
      const hasIsland = selCardsObj.some(c => c.land_type === 'island');
      if (hasIsland && selCardsObj.length === 2) {
        btnCounter.disabled = false;
      }
    }
  }
}

// Triggered on strategy radio changes
function onStrategyChange(value) {
  counterStrategy = value;
  localStorage.setItem('basic_land_counter_strategy', counterStrategy);
  showToast(`Counter strategy changed to: ${value.replace(/_/g, ' ')}`, 'success');
  
  // Re-run checking in case game is currently waiting on us
  handleCounterAutoRun();
}

function getSelectedCounterStrategy() {
  return counterStrategy;
}

// Parse pending play format: "Card(mountain, id=abc)"
function parsePendingPlay(str) {
  if (!str) return null;
  const match = str.match(/Card\((\w+),\s*id=([^)]+)\)/);
  if (match) {
    return {
      land_type: match[1],
      card_id: match[2]
    };
  }
  return null;
}

// Append new rows into matching Battle Journal
function appendEvents(events) {
  if (!events || events.length === 0) return;
  const list = document.getElementById('event-log-list');

  events.forEach(evt => {
    const li = document.createElement('li');
    li.className = 'log-entry';

    if (evt.includes('countered')) {
      li.classList.add('log-countered');
    } else if (evt.includes('wins!')) {
      li.classList.add('log-win');
    }

    if (evt.startsWith('[T')) {
      const match = evt.match(/^(\[T\d+\])(.*)/);
      if (match) {
        const turnSpan = document.createElement('span');
        turnSpan.className = 'log-turn';
        turnSpan.textContent = match[1] + ' ';
        li.appendChild(turnSpan);

        const restText = document.createTextNode(match[2]);
        li.appendChild(restText);
        list.appendChild(li);
        return;
      }
    }

    li.textContent = evt;
    list.appendChild(li);
  });

  list.scrollTop = list.scrollHeight;
}

// ==========================================
// Game-over overlay
// ==========================================
function showGameOverOverlay(state) {
  const overlay = document.getElementById('game-over-overlay');
  const title   = document.getElementById('game-over-title');
  const reason  = document.getElementById('game-over-reason');

  const myName = playerName || 'You';
  const isWinner = state.winner_name === myName;

  if (isWinner) {
    title.textContent = 'VICTORY';
    title.style.background = 'linear-gradient(90deg, #fbbf24, #f59e0b)';
    title.style.webkitBackgroundClip = 'text';
    title.style.webkitTextFillColor = 'transparent';
    reason.textContent = 'Congratulations — you won the match!';
  } else {
    title.textContent = 'DEFEAT';
    title.style.background = 'linear-gradient(90deg, #f87171, #dc2626)';
    title.style.webkitBackgroundClip = 'text';
    title.style.webkitTextFillColor = 'transparent';
    reason.textContent = state.winner_name
      ? `${state.winner_name} has won the match.`
      : 'The game has ended.';
  }

  overlay.style.display = 'block';
}

function returnToLobby() {
  const overlay = document.getElementById('game-over-overlay');
  overlay.style.display = 'none';
  delete overlay.dataset.shown;

  // Close the game WS and clear game state — keep the player token
  if (gameWs) {
    gameWs.close();
    gameWs = null;
  }
  stopGamePing();

  localStorage.removeItem('basic_land_game_id');
  gameId    = null;
  gameState = null;
  selectedCardsInHand = [];
  selectedTargetCard  = null;

  // Transition screens
  document.getElementById('game-screen').classList.add('hidden');
  document.getElementById('lobby-screen').classList.remove('hidden');

  // Put the player back in the waiting lobby
  apiCall('/lobby/join', 'POST', { name: playerName })
    .then(data => {
      playerToken = data.player_token;
      playerId    = data.player_id;
      playerName  = data.name;
      localStorage.setItem('basic_land_player_token', playerToken);
      localStorage.setItem('basic_land_player_id', playerId);
      localStorage.setItem('basic_land_player_name', playerName);

      document.getElementById('join-form').style.display = 'none';
      document.getElementById('lobby-panel').style.display = 'block';
      document.getElementById('player-profile-name').textContent = playerName;

      initLobbyWs();
      refreshLobby();
      showToast(`Back in the lobby as ${playerName}!`, 'success');
    })
    .catch(err => {
      // Name may already be taken (e.g. same server session) — fall back to join form
      showToast(err.message || 'Could not re-join lobby. Please re-register.', 'error');
      document.getElementById('join-form').style.display = 'block';
      document.getElementById('lobby-panel').style.display = 'none';
    });
}

// Forfeit and clean up
function forfeitAndExit() {
  if (confirm('Are you sure you want to forfeit/exit the game? This will reset your session.')) {
    // Notify the server
    try {
      sendGameAction('FORFEIT');
    } catch (e) {
      console.warn('Failed to send forfeit action:', e);
    }

    // Give a tiny delay to ensure the WebSocket transmission is sent before closing
    setTimeout(() => {
      localStorage.removeItem('basic_land_game_id');
      localStorage.removeItem('basic_land_player_token');
      localStorage.removeItem('basic_land_player_id');

      if (gameWs) {
        gameWs.close();
        gameWs = null;
      }
      stopGamePing();

      // Reset variables
      playerToken = null;
      playerId = null;
      playerName = null;
      gameId = null;
      gameState = null;

      // Reset UI
      document.getElementById('game-screen').classList.add('hidden');
      document.getElementById('lobby-screen').classList.remove('hidden');
      document.getElementById('join-form').style.display = 'block';
      document.getElementById('lobby-panel').style.display = 'none';

      showToast('Exited game session. Register a new name to start fresh.', 'success');
    }, 50);
  }
}

// ==========================================
// Phaser Initialization
// ==========================================
function initPhaserGame() {
  const config = {
    type: Phaser.AUTO,
    parent: 'game-canvas-container',

    scale: {
      mode: Phaser.Scale.FIT,
      autoCenter: Phaser.Scale.CENTER_BOTH,
      width: 960,
      height: 700
    },

    backgroundColor: '#0f172a',
    scene: [BasicLandGameScene]
  };

  phaserGame = new Phaser.Game(config);
}

function handleResize() {
  updateOrientationUI();

  if (!phaserGame) {
    return;
  }

  const container =
    document.getElementById('game-canvas-container');

  phaserGame.scale.refresh();

  if (gameScene && gameScene.drawBoard) {
    gameScene.drawBoard();
  }
}

// ==========================================
// UI Event Bindings
// ==========================================
document.addEventListener('DOMContentLoaded', () => {
  // Bind join button
  document.getElementById('btn-join-lobby').onclick = joinLobby;
  document.getElementById('btn-refresh-lobby').onclick = refreshLobby;
  document.getElementById('btn-leave-lobby').onclick = leaveLobby;
  document.getElementById('btn-exit-game').onclick = forfeitAndExit;
  document.getElementById('btn-return-lobby').onclick = returnToLobby;

  // Lobby username Enter key bind
  document.getElementById('username-input').addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
      joinLobby();
    }
  });

  // Action controls listeners
  document.getElementById('btn-play-land').onclick = () => {
    if (selectedCardsInHand.length === 1) {
      sendGameAction('PLAY_LAND', { card_id: selectedCardsInHand[0] });
      selectedCardsInHand = [];
      updateControls();
    }
  };

  document.getElementById('btn-pass-turn').onclick = () => {
    sendGameAction('PASS_TURN');
    selectedCardsInHand = [];
    updateControls();
  };

  document.getElementById('btn-allow-play').onclick = () => {
    sendGameAction('ALLOW_LAND');
    selectedCardsInHand = [];
    updateControls();
  };

  document.getElementById('btn-counter-play').onclick = () => {
    if (selectedCardsInHand.length === 2) {
      // Find Island
      const myHand = gameState.my_hand || [];
      const selCardsObj = myHand.filter(c => selectedCardsInHand.includes(c.card_id));
      const island = selCardsObj.find(c => c.land_type === 'island');
      const other = selCardsObj.find(c => c.card_id !== island.card_id);

      if (island && other) {
        sendGameAction('COUNTER_LAND', {
          card_id: island.card_id,
          counter_second_card_id: other.card_id
        });
        selectedCardsInHand = [];
        updateControls();
      }
    }
  };

  document.getElementById('btn-reset-selection').onclick = () => {
    selectedCardsInHand = [];
    if (gameScene) gameScene.drawBoard();
    updateControls();
  };

  // Strategy Radio group selections
  const strategyOptions = document.querySelectorAll('#strategy-radio-group .radio-option');
  strategyOptions.forEach(opt => {
    const radio = opt.querySelector('input[type="radio"]');
    
    // Set initial checked state
    if (radio.value === counterStrategy) {
      radio.checked = true;
      opt.classList.add('selected');
    } else {
      radio.checked = false;
      opt.classList.remove('selected');
    }

    radio.addEventListener('change', () => {
      // Remove 'selected' styling from all options
      strategyOptions.forEach(o => o.classList.remove('selected'));
      
      if (radio.checked) {
        opt.classList.add('selected');
        onStrategyChange(radio.value);
      }
    });
  });

  // Rules accordion toggle
  const rulesToggle = document.getElementById('rules-toggle');
  const rulesBody = document.getElementById('rules-body');
  rulesToggle.addEventListener('click', () => {
    const isExpanded = rulesToggle.getAttribute('aria-expanded') === 'true';
    rulesToggle.setAttribute('aria-expanded', String(!isExpanded));
    if (isExpanded) {
      rulesBody.hidden = true;
    } else {
      rulesBody.hidden = false;
    }
  });

  setTimeout(updateOrientationUI, 0);  // defer one tick

  window.addEventListener('resize', handleResize);
  window.addEventListener('orientationchange', handleResize);

  // Reconnection Check on page load
  checkSessionReconstruction();
});

async function checkSessionReconstruction() {
  if (playerToken && gameId) {
    try {
      showToast('Restoring game session...', 'success');
      
      // Attempt to load current game state
      const state = await apiCall(`/games/${gameId}/state`);
      
      // Restoring successful, trigger UI transitions
      document.getElementById('lobby-screen').classList.add('hidden');
      document.getElementById('game-screen').classList.remove('hidden');

      const seat = state.my_seat;
      const oppSeat = 1 - seat;
      const oppName = state.players[oppSeat].name || 'Opponent';

      document.getElementById('opponent-name-indicator').textContent = oppName;
      document.getElementById('seat-indicator').textContent = seat;

      if (!phaserGame) {
        initPhaserGame();
      }

      initGameWs();
      // On connection, WS automatically pushes the current state snapshot
    } catch (e) {
      console.warn('Could not restore game session:', e);
      // Clean up game id but keep player info
      localStorage.removeItem('basic_land_game_id');
      gameId = null;
      
      if (e.status === 401) {
        localStorage.removeItem('basic_land_player_token');
        localStorage.removeItem('basic_land_player_id');
        localStorage.removeItem('basic_land_player_name');
        playerToken = null;
        playerId = null;
        playerName = null;
        
        document.getElementById('join-form').style.display = 'block';
        document.getElementById('lobby-panel').style.display = 'none';
      } else {
        await checkLobbyReconstruction();
      }
    }
  } else {
    await checkLobbyReconstruction();
  }
}

async function checkLobbyReconstruction() {
  if (playerToken && playerName) {
    try {
      // Validate the token by fetching the waiting list
      const data = await apiCall('/lobby/waiting');
      
      // Player exists and token is valid, skip join form and enter lobby
      document.getElementById('join-form').style.display = 'none';
      document.getElementById('lobby-panel').style.display = 'block';
      document.getElementById('player-profile-name').textContent = playerName;

      // Restore reservation banner if it was set before the page reload
      const savedReservation = localStorage.getItem('basic_land_reserved_for');
      const banner = document.getElementById('reservation-banner');
      if (savedReservation && banner) {
        document.getElementById('reservation-target-name').textContent = savedReservation;
        banner.style.display = 'flex';
      }
      
      initLobbyWs();
      updateWaitingList(data.waiting);
    } catch (e) {
      console.warn('Player token is invalid, clearing session:', e);
      localStorage.removeItem('basic_land_player_token');
      localStorage.removeItem('basic_land_player_id');
      localStorage.removeItem('basic_land_player_name');
      playerToken = null;
      playerId = null;
      playerName = null;
      
      // Reset UI back to registration/login
      document.getElementById('join-form').style.display = 'block';
      document.getElementById('lobby-panel').style.display = 'none';
    }
  }
}

// ==========================================
// Toast Notifications
// ==========================================
let toastTimeout = null;
function showToast(msg, type = 'success') {
  const toast = document.getElementById('toast-element');
  if (!toast) return;

  toast.textContent = msg;
  toast.className = 'toast-msg show';
  
  if (type === 'success') {
    toast.classList.add('toast-success');
  } else if (type === 'error') {
    toast.classList.add('toast-error');
  }

  if (toastTimeout) {
    clearTimeout(toastTimeout);
  }

  toastTimeout = setTimeout(() => {
    toast.className = 'toast-msg';
  }, 3000);
}

// Layout helper for horizontal positioning
function getCardXCoordinates(centerX, totalWidth, count, cardWidth) {
  if (count <= 0) return [];
  if (count === 1) return [centerX];

  const spacing = Math.min(cardWidth + 12, totalWidth / (count - 1));
  const startX = centerX - (spacing * (count - 1)) / 2;
  
  const coords = [];
  for (let i = 0; i < count; i++) {
    coords.push(startX + i * spacing);
  }
  return coords;
}