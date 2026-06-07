/**
 * Basic Land Game - Phaser Frontend
 * Main game scenes: Lobby and Game
 */

// ============================================================================
// LOBBY SCENE
// ============================================================================

class LobbyScene extends Phaser.Scene {
    constructor() {
        super({ key: 'LobbyScene' });
    }

    async init() {
        this.playerName = null;
        this.waitingPlayers = [];
        this.selectedOpponent = null;
        this.nameInput = null;
        this.joinButton = null;
        this.statusText = null;
    }

    create() {
        // Get HTML elements
        this.nameInput = document.getElementById('player-name-input');
        this.joinButton = document.getElementById('join-button');
        this.modal = document.getElementById('name-input-modal');
        this.statusText = document.getElementById('status-text');
        
        // Show modal
        this.modal.classList.remove('hidden');
        
        // Set up button handler
        this.joinButton.addEventListener('click', () => this.handleJoin());
        this.nameInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') this.handleJoin();
        });
        
        // Focus on input
        this.nameInput.focus();

        // Background
        this.cameras.main.setBackgroundColor('#1a1a2e');

        // Title
        this.add.text(400, 50, 'Basic Land Game', {
            fontSize: '48px',
            fill: '#00ff00',
            fontFamily: 'Arial',
            fontStyle: 'bold',
        }).setOrigin(0.5);

        // Waiting players section
        this.add.text(400, 150, 'Waiting for Opponent:', {
            fontSize: '20px',
            fill: '#ffff00',
            fontFamily: 'Arial',
        }).setOrigin(0.5);

        this.waitingPlayersContainer = this.add.container(400, 220);
    }

    async handleJoin() {
        const name = this.nameInput.value.trim();
        if (!name) {
            this.updateStatus('Please enter a name', 'error');
            return;
        }

        try {
            this.updateStatus('Joining lobby...', 'warning');
            this.joinButton.disabled = true;

            await apiClient.joinLobby(name);
            this.playerName = name;

            // Hide modal
            this.modal.classList.add('hidden');

            // Connect to lobby WebSocket
            await apiClient.connectLobbyWs(
                (msg) => this.handleWsMessage(msg),
                (err) => this.handleWsError(err)
            );

            this.updateStatus(`Connected as ${name}`, 'success');

            // Start polling for waiting players
            this.pollWaitingPlayers();

            // Keep-alive ping
            setInterval(() => apiClient.sendLobbyPing(), 30000);
        } catch (error) {
            console.error('Failed to join lobby:', error);
            this.updateStatus(`Error: ${error.message}`, 'error');
            this.joinButton.disabled = false;
        }
    }

    updateStatus(message, level = 'info') {
        if (this.statusText) {
            this.statusText.textContent = message;
            this.statusText.className = 'status-text ' + level;
        }
    }

    async pollWaitingPlayers() {
        while (apiClient.isConnected() && this.scene.isActive()) {
            try {
                this.waitingPlayers = await apiClient.getWaitingPlayers();
                this.renderWaitingPlayers();
            } catch (error) {
                console.error('Failed to poll waiting players:', error);
            }
            await new Promise(resolve => setTimeout(resolve, 1000));
        }
    }

    renderWaitingPlayers() {
        // Clear previous rendering
        this.waitingPlayersContainer.removeAll(true);

        const otherPlayers = this.waitingPlayers.filter(p => p.name !== this.playerName);

        if (otherPlayers.length === 0) {
            this.add.text(400, 220, 'Waiting for opponents...', {
                fontSize: '16px',
                fill: '#888888',
                fontFamily: 'Arial',
            }).setOrigin(0.5);
            return;
        }

        let y = 0;
        otherPlayers.forEach((player, index) => {
            const playerBg = this.add.rectangle(
                400, 220 + y, 350, 45,
                this.selectedOpponent === player.player_id ? 0x004400 : 0x1a1a2e
            );
            playerBg.setStrokeStyle(2, 0x00ff00);
            playerBg.setInteractive({ useHandCursor: true });
            playerBg.on('pointerdown', () => this.selectOpponent(player));

            this.add.text(400, 220 + y, `${player.name}`, {
                fontSize: '16px',
                fill: '#00ff00',
                fontFamily: 'Arial',
            }).setOrigin(0.5);

            y += 50;
        });

        // Challenge button (if opponent selected)
        if (this.selectedOpponent) {
            const challengeButton = this.add.rectangle(400, 220 + y + 40, 200, 50, 0xff6600);
            challengeButton.setInteractive({ useHandCursor: true });
            challengeButton.on('pointerdown', () => this.handleChallenge());
            this.add.text(400, 220 + y + 40, 'Challenge', {
                fontSize: '18px',
                fill: '#000000',
                fontFamily: 'Arial',
                fontStyle: 'bold',
            }).setOrigin(0.5);
        }
    }

    selectOpponent(player) {
        this.selectedOpponent = player.player_id;
        this.renderWaitingPlayers();
    }

    async handleChallenge() {
        if (!this.selectedOpponent) return;

        try {
            this.updateStatus('Challenging opponent...', 'warning');
            const result = await apiClient.challengeOpponent(this.selectedOpponent);
            // Game started - switch to game scene
            this.scene.start('GameScene', {
                gameId: result.game_id,
                yourSeat: result.your_seat,
                opponentName: result.opponent_name,
            });
        } catch (error) {
            console.error('Failed to challenge:', error);
            this.updateStatus(`Error: ${error.message}`, 'error');
        }
    }

    handleWsMessage(message) {
        if (message.type === 'game_started') {
            console.log('Game started!', message);
            this.scene.start('GameScene', {
                gameId: message.game_id,
                yourSeat: message.your_seat,
                opponentName: message.opponent_name,
            });
        } else if (message.type === 'lobby_update') {
            this.waitingPlayers = message.waiting;
            this.renderWaitingPlayers();
        }
    }

    handleWsError(error) {
        console.error('WebSocket error:', error);
        this.updateStatus('Connection lost!', 'error');
    }

    shutdown() {
        // Clean up modal
        if (this.modal) {
            this.modal.classList.add('hidden');
        }
        // Clean up event listeners
        if (this.joinButton) {
            this.joinButton.removeEventListener('click', () => this.handleJoin());
        }
        if (this.nameInput) {
            this.nameInput.removeEventListener('keydown', () => {});
        }
        apiClient.closeLobbyWs();
    }
}

// ============================================================================
// GAME SCENE
// ============================================================================

class GameScene extends Phaser.Scene {
    constructor() {
        super({ key: 'GameScene' });
    }

    init(data) {
        this.gameId = data.gameId;
        this.yourSeat = data.yourSeat;
        this.opponentName = data.opponentName;
        this.gameState = null;
        this.selectedCard = null;
        this.selectedAction = null;
        this.targetOpponentCard = null;
    }

    async create() {
        // Background
        this.cameras.main.setBackgroundColor('#0d1b2a');

        // Clear status text from previous scene
        const statusText = document.getElementById('status-text');
        if (statusText) {
            statusText.textContent = '';
            statusText.className = 'status-text';
        }

        // Close lobby WebSocket
        apiClient.closeLobbyWs();

        // Connect to game WebSocket
        try {
            await apiClient.connectGameWs(
                this.gameId,
                (msg) => this.handleGameMessage(msg),
                (err) => this.handleGameError(err)
            );
        } catch (error) {
            console.error('Failed to connect to game:', error);
        }

        // Fetch initial game state
        try {
            this.gameState = await apiClient.getGameState(this.gameId);
            this.render();
        } catch (error) {
            console.error('Failed to fetch game state:', error);
        }

        // Keep-alive ping
        setInterval(() => apiClient.sendGamePing(), 30000);
    }

    async handleGameMessage(message) {
        if (message.type === 'game_state') {
            this.gameState = message.state;
            this.render();
        } else if (message.type === 'action_result') {
            console.log('Action result:', message);
            if (!message.success) {
                this.showError(message.message);
            }
        } else if (message.type === 'error') {
            this.showError(message.message);
        }
    }

    handleGameError(error) {
        console.error('Game WebSocket error:', error);
    }

    render() {
        // Clear previous scene
        this.children.removeAll(true);

        if (!this.gameState) return;

        // Header with game info
        this.add.text(400, 15, `Basic Land Game - Turn ${this.gameState.turn_number}`, {
            fontSize: '18px',
            fill: '#00ff00',
            fontFamily: 'Arial',
            fontStyle: 'bold',
        }).setOrigin(0.5);

        // Phase info
        const phaseText = this.gameState.phase === 'GAME_OVER'
            ? `GAME OVER - ${this.gameState.winner_name} wins!`
            : `Phase: ${this.gameState.phase} | ${this.gameState.whose_turn === 'you' ? 'Your Turn' : 'Opponent\'s Turn'}`;
        this.add.text(400, 35, phaseText, {
            fontSize: '12px',
            fill: this.gameState.whose_turn === 'you' ? '#ffff00' : '#888888',
            fontFamily: 'Arial',
        }).setOrigin(0.5);

        // Board layout
        this.renderOpponentZone();
        this.renderPlayerZone();
        this.renderHand();
        this.renderEventLog();
        this.renderActions();
    }

    renderOpponentZone() {
        const opponent = this.gameState.players[1 - this.yourSeat];
        const y = 80;

        this.add.text(50, y, `${this.opponentName}`, {
            fontSize: '16px',
            fill: '#ff6b6b',
            fontFamily: 'Arial',
            fontStyle: 'bold',
        });

        // Opponent's stats
        this.add.text(50, y + 25, `Hand: ${opponent.hand_size}`, {
            fontSize: '12px',
            fill: '#cccccc',
        });
        this.add.text(150, y + 25, `Library: ${opponent.library_size}`, {
            fontSize: '12px',
            fill: '#cccccc',
        });
        this.add.text(280, y + 25, `Graveyard: ${opponent.graveyard.length}`, {
            fontSize: '12px',
            fill: '#cccccc',
        });

        // Opponent's hand (compact display on the right side)
        this.add.text(650, y, "Opponent's Hand:", {
            fontSize: '11px',
            fill: '#ffaa00',
            fontFamily: 'Arial',
        });
        
        // Show hand cards in a compact 2-row grid on the right
        let cardX = 650;
        let cardY = y + 25;
        let cardsPerRow = 5;
        
        // Build map of revealed cards for quick lookup
        const revealedMap = {};
        if (opponent.revealed_hand && opponent.revealed_hand.length > 0) {
            opponent.revealed_hand.forEach(card => {
                revealedMap[card.card_id] = card;
            });
        }
        
        // Render all hand positions as card backs first
        for (let i = 0; i < opponent.hand_size; i++) {
            if (i > 0 && i % cardsPerRow === 0) {
                cardY += 65;
                cardX = 650;
            }
            this.createCompactCardBackDisplay(cardX, cardY);
            cardX += 60;
        }
        
        // Now render revealed cards on top (from the server's current revealed_hand array)
        if (opponent.revealed_hand && opponent.revealed_hand.length > 0) {
            cardX = 650;
            cardY = y + 25;
            let revealedIndex = 0;
            
            opponent.revealed_hand.forEach((card, idx) => {
                if (revealedIndex > 0 && revealedIndex % cardsPerRow === 0) {
                    cardY += 65;
                    cardX = 650;
                }
                
                const isTarget = this.targetOpponentCard === card.card_id;
                this.createCompactOpponentCardDisplay(cardX, cardY, card, idx, isTarget);
                
                cardX += 60;
                revealedIndex++;
            });
        }

        // Opponent's active lands
        this.add.text(50, y + 60, 'Active:', {
            fontSize: '12px',
            fill: '#ffff00',
            fontFamily: 'Arial',
        });
        let x = 50;
        opponent.active.forEach((card, i) => {
            this.createCardDisplay(x, y + 85, card, `opponent-active-${i}`);
            x += 85;
        });

        // Opponent's graveyard
        this.add.text(50, y + 150, 'Graveyard:', {
            fontSize: '12px',
            fill: '#ffff00',
            fontFamily: 'Arial',
        });
        x = 50;
        opponent.graveyard.slice(0, 6).forEach((card, i) => {
            this.createCardDisplay(x, y + 175, card, `opponent-gy-${i}`, 0.7);
            x += 70;
        });
    }

    renderPlayerZone() {
        const player = this.gameState.players[this.yourSeat];
        const y = 320;

        this.add.text(50, y, `You (Seat ${this.yourSeat})`, {
            fontSize: '16px',
            fill: '#6bff6b',
            fontFamily: 'Arial',
            fontStyle: 'bold',
        });

        // Your stats
        this.add.text(50, y + 25, `Hand: ${player.hand_size}`, {
            fontSize: '12px',
            fill: '#cccccc',
        });
        this.add.text(150, y + 25, `Library: ${player.library_size}`, {
            fontSize: '12px',
            fill: '#cccccc',
        });
        this.add.text(280, y + 25, `Graveyard: ${player.graveyard.length}`, {
            fontSize: '12px',
            fill: '#cccccc',
        });

        // Your active lands
        this.add.text(50, y + 50, 'Active:', {
            fontSize: '12px',
            fill: '#ffff00',
            fontFamily: 'Arial',
        });
        let x = 50;
        player.active.forEach((card, i) => {
            this.createCardDisplay(x, y + 75, card, `player-active-${i}`);
            x += 85;
        });

        // Your graveyard
        this.add.text(50, y + 140, 'Graveyard:', {
            fontSize: '12px',
            fill: '#ffff00',
            fontFamily: 'Arial',
        });
        x = 50;
        player.graveyard.slice(0, 6).forEach((card, i) => {
            this.createCardDisplay(x, y + 165, card, `player-gy-${i}`, 0.7);
            x += 70;
        });
    }

    renderHand() {
        this.add.text(50, 530, 'Your Hand:', {
            fontSize: '14px',
            fill: '#ffff00',
            fontFamily: 'Arial',
            fontStyle: 'bold',
        });

        let x = 50;
        this.gameState.my_hand.forEach((card, i) => {
            const isSelected = this.selectedCard?.card_id === card.card_id;
            this.createHandCardDisplay(x, 555, card, i, isSelected);
            x += 90;
        });
    }

    renderEventLog() {
        const x = 50;
        const y = 220;

        this.add.text(x, y, 'Event Log:', {
            fontSize: '11px',
            fill: '#ffff00',
            fontFamily: 'Arial',
            fontStyle: 'bold',
        });

        const events = this.gameState.new_events || [];
        let ty = y + 20;
        events.slice(-3).forEach(event => {
            this.add.text(x + 5, ty, event, {
                fontSize: '8px',
                fill: '#cccccc',
                fontFamily: 'Courier',
                wordWrap: { width: 300 },
            });
            ty += 30;
        });
    }

    renderActions() {
        const y = 320;
        const x = 650;

        this.add.text(x, y, 'Actions:', {
            fontSize: '12px',
            fill: '#ffff00',
            fontFamily: 'Arial',
            fontStyle: 'bold',
        });

        if (this.gameState.whose_turn !== 'you') {
            this.add.text(x, y + 30, 'Waiting for opponent...', {
                fontSize: '11px',
                fill: '#888888',
            });
            return;
        }

        let by = y + 30;

        if (this.gameState.phase === 'PLAY_OR_PASS') {
            const playButton = this.add.rectangle(x + 35, by, 70, 30, 0x00aa00);
            playButton.setInteractive({ useHandCursor: true });
            playButton.on('pointerdown', () => this.playSelectedCard());
            this.add.text(x + 35, by, 'Play', {
                fontSize: '11px',
                fill: '#000000',
                fontFamily: 'Arial',
            }).setOrigin(0.5);
            by += 35;

            const passButton = this.add.rectangle(x + 35, by, 70, 30, 0xaa0000);
            passButton.setInteractive({ useHandCursor: true });
            passButton.on('pointerdown', () => this.submitAction('PASS_TURN'));
            this.add.text(x + 35, by, 'Pass', {
                fontSize: '11px',
                fill: '#000000',
                fontFamily: 'Arial',
            }).setOrigin(0.5);
        } else if (this.gameState.phase === 'AWAIT_COUNTER') {
            const allowButton = this.add.rectangle(x + 35, by, 70, 30, 0x00aa00);
            allowButton.setInteractive({ useHandCursor: true });
            allowButton.on('pointerdown', () => this.submitAction('ALLOW_LAND'));
            this.add.text(x + 35, by, 'Allow', {
                fontSize: '11px',
                fill: '#000000',
                fontFamily: 'Arial',
            }).setOrigin(0.5);
            by += 35;

            const counterButton = this.add.rectangle(x + 35, by, 70, 30, 0xaa0000);
            counterButton.setInteractive({ useHandCursor: true });
            counterButton.on('pointerdown', () => this.prepareCounter());
            this.add.text(x + 35, by, 'Counter', {
                fontSize: '11px',
                fill: '#000000',
                fontFamily: 'Arial',
            }).setOrigin(0.5);
        } else if (this.gameState.phase === 'RESOLVE_EFFECT') {
            const pendingCard = this.gameState.pending_play;
            
            if (pendingCard && pendingCard.includes('swamp')) {
                if (this.targetOpponentCard) {
                    const submitButton = this.add.rectangle(x + 35, by, 70, 30, 0x00aa00);
                    submitButton.setInteractive({ useHandCursor: true });
                    submitButton.on('pointerdown', () => this.submitAction('SWAMP_DISCARD', null, this.targetOpponentCard));
                    this.add.text(x + 35, by, 'Discard', {
                        fontSize: '11px',
                        fill: '#000000',
                        fontFamily: 'Arial',
                    }).setOrigin(0.5);
                    by += 35;
                    this.add.text(x, by, 'Selected card to discard', {
                        fontSize: '10px',
                        fill: '#00ff00',
                    });
                } else {
                    this.add.text(x, by, 'Choose card to discard', {
                        fontSize: '11px',
                        fill: '#ffff00',
                    });
                }
            } else if (pendingCard && pendingCard.includes('mountain')) {
                this.add.text(x, by, 'Choose opponent land to destroy', {
                    fontSize: '11px',
                    fill: '#ffff00',
                });
            } else if (pendingCard && pendingCard.includes('forest')) {
                this.add.text(x, by, 'Choose graveyard land to return', {
                    fontSize: '11px',
                    fill: '#ffff00',
                });
            } else if (pendingCard && pendingCard.includes('plains')) {
                this.add.text(x, by, 'Choose land effect to copy', {
                    fontSize: '11px',
                    fill: '#ffff00',
                });
            } else {
                this.add.text(x, by, 'Choose target...', {
                    fontSize: '11px',
                    fill: '#ffff00',
                });
            }
        }
    }

    createCardDisplay(x, y, card, key, scale = 1.0) {
        const colors = {
            forest: 0x228B22,
            island: 0x4169E1,
            mountain: 0xFF4500,
            plains: 0xF5F5DC,
            swamp: 0x2F4F4F,
        };

        const textColors = {
            forest: '#ffffff',
            island: '#ffffff',
            mountain: '#ffffff',
            plains: '#000000',
            swamp: '#ffffff',
        };

        const width = 75 * scale;
        const height = 95 * scale;
        
        // Create card background
        const bg = this.add.rectangle(x, y, width, height, colors[card.land_type]);
        bg.setStrokeStyle(2, 0xffff00);
        bg.setDepth(1);

        // Add land type text
        this.add.text(x, y - 15 * scale, card.land_type.toUpperCase(), {
            fontSize: `${12 * scale}px`,
            fill: textColors[card.land_type],
            fontFamily: 'Arial',
            fontStyle: 'bold',
            align: 'center',
        }).setOrigin(0.5).setDepth(2);

        // Add card ID
        this.add.text(x, y + 25 * scale, card.card_id.substring(0, 6), {
            fontSize: `${8 * scale}px`,
            fill: textColors[card.land_type],
            fontFamily: 'Courier',
            align: 'center',
        }).setOrigin(0.5).setDepth(2);

        return bg;
    }

    createHandCardDisplay(x, y, card, index, isSelected) {
        const colors = {
            forest: 0x228B22,
            island: 0x4169E1,
            mountain: 0xFF4500,
            plains: 0xF5F5DC,
            swamp: 0x2F4F4F,
        };

        const textColors = {
            forest: '#ffffff',
            island: '#ffffff',
            mountain: '#ffffff',
            plains: '#000000',
            swamp: '#ffffff',
        };

        const width = 80;
        const height = 110;
        
        // Create card background
        const bg = this.add.rectangle(x, y, width, height, colors[card.land_type]);
        bg.setStrokeStyle(isSelected ? 4 : 2, isSelected ? 0x00ff00 : 0xffff00);
        bg.setInteractive({ useHandCursor: true });
        bg.on('pointerdown', () => this.selectCard(card, index));
        bg.setDepth(1);

        // Add land type text
        this.add.text(x, y - 35, card.land_type.toUpperCase(), {
            fontSize: '14px',
            fill: textColors[card.land_type],
            fontFamily: 'Arial',
            fontStyle: 'bold',
            align: 'center',
        }).setOrigin(0.5).setDepth(2);

        // Add card ID
        this.add.text(x, y + 30, `ID: ${card.card_id.substring(0, 4)}`, {
            fontSize: '9px',
            fill: textColors[card.land_type],
            fontFamily: 'Courier',
            align: 'center',
        }).setOrigin(0.5).setDepth(2);

        return bg;
    }

    createOpponentHandCardDisplay(x, y, card, index, isSelected) {
        const colors = {
            forest: 0x228B22,
            island: 0x4169E1,
            mountain: 0xFF4500,
            plains: 0xF5F5DC,
            swamp: 0x2F4F4F,
        };

        const textColors = {
            forest: '#ffffff',
            island: '#ffffff',
            mountain: '#ffffff',
            plains: '#000000',
            swamp: '#ffffff',
        };

        const width = 65;
        const height = 90;
        
        // Create card background
        const bg = this.add.rectangle(x, y, width, height, colors[card.land_type]);
        bg.setStrokeStyle(isSelected ? 4 : 2, isSelected ? 0xff6b6b : 0xffaa00);
        bg.setInteractive({ useHandCursor: true });
        bg.on('pointerdown', () => this.selectOpponentHandCard(card));
        bg.setDepth(1);

        // Add land type text
        this.add.text(x, y - 25, card.land_type.toUpperCase(), {
            fontSize: '11px',
            fill: textColors[card.land_type],
            fontFamily: 'Arial',
            fontStyle: 'bold',
            align: 'center',
        }).setOrigin(0.5).setDepth(2);

        // Add card ID
        this.add.text(x, y + 25, `ID: ${card.card_id.substring(0, 3)}`, {
            fontSize: '7px',
            fill: textColors[card.land_type],
            fontFamily: 'Courier',
            align: 'center',
        }).setOrigin(0.5).setDepth(2);

        return bg;
    }

    createCardBackDisplay(x, y) {
        const width = 65;
        const height = 90;
        
        // Create card back background
        const bg = this.add.rectangle(x, y, width, height, 0x1a4d7d);
        bg.setStrokeStyle(2, 0x4a9eff);
        bg.setDepth(1);

        // Add decorative pattern
        this.add.text(x, y - 20, '?', {
            fontSize: '28px',
            fill: '#4a9eff',
            fontFamily: 'Arial',
            fontStyle: 'bold',
            align: 'center',
        }).setOrigin(0.5).setDepth(2);

        // Add border detail
        this.add.text(x, y + 25, 'CARD', {
            fontSize: '7px',
            fill: '#4a9eff',
            fontFamily: 'Arial',
            align: 'center',
        }).setOrigin(0.5).setDepth(2);

        return bg;
    }

    createCompactCardBackDisplay(x, y) {
        const width = 50;
        const height = 60;
        
        // Create card back background
        const bg = this.add.rectangle(x, y, width, height, 0x1a4d7d);
        bg.setStrokeStyle(1, 0x4a9eff);
        bg.setDepth(1);

        // Add decorative pattern
        this.add.text(x, y - 10, '?', {
            fontSize: '18px',
            fill: '#4a9eff',
            fontFamily: 'Arial',
            fontStyle: 'bold',
            align: 'center',
        }).setOrigin(0.5).setDepth(2);

        return bg;
    }

    createCompactOpponentCardDisplay(x, y, card, index, isSelected) {
        const colors = {
            forest: 0x228B22,
            island: 0x4169E1,
            mountain: 0xFF4500,
            plains: 0xF5F5DC,
            swamp: 0x2F4F4F,
        };

        const textColors = {
            forest: '#ffffff',
            island: '#ffffff',
            mountain: '#ffffff',
            plains: '#000000',
            swamp: '#ffffff',
        };

        const width = 50;
        const height = 60;
        
        // Create card background
        const bg = this.add.rectangle(x, y, width, height, colors[card.land_type]);
        bg.setStrokeStyle(isSelected ? 3 : 1, isSelected ? 0xff6b6b : 0xffaa00);
        bg.setInteractive({ useHandCursor: true });
        bg.on('pointerdown', () => this.selectOpponentHandCard(card));
        bg.setDepth(1);

        // Add land type abbreviation
        const abbrev = card.land_type.substring(0, 1).toUpperCase();
        this.add.text(x, y, abbrev, {
            fontSize: '16px',
            fill: textColors[card.land_type],
            fontFamily: 'Arial',
            fontStyle: 'bold',
            align: 'center',
        }).setOrigin(0.5).setDepth(2);

        return bg;
    }

    selectCard(card, index) {
        this.selectedCard = card;
        this.render();
    }

    selectOpponentHandCard(card) {
        this.targetOpponentCard = card.card_id;
        this.render();
    }

    async playSelectedCard() {
        if (!this.selectedCard) {
            this.showError('Please select a card to play');
            return;
        }

        try {
            await this.submitAction('PLAY_LAND', this.selectedCard.card_id);
            this.selectedCard = null;
        } catch (error) {
            console.error('Failed to play card:', error);
        }
    }

    prepareCounter() {
        // This is more complex - need to select two cards
        this.showError('Counter functionality requires two-card selection (coming soon)');
    }

    async submitAction(actionType, cardId = null, targetCardId = null) {
        const action = { action_type: actionType };
        if (cardId) action.card_id = cardId;
        if (targetCardId) action.target_card_id = targetCardId;

        try {
            apiClient.submitActionViaWs(action);
            // Clear selection after submitting
            this.selectedCard = null;
            this.targetOpponentCard = null;
        } catch (error) {
            console.error('Failed to submit action:', error);
            this.showError(`Action failed: ${error.message}`);
        }
    }

    showError(message) {
        console.error('Error:', message);
        // Update HTML status text
        const statusText = document.getElementById('status-text');
        if (statusText) {
            statusText.textContent = message;
            statusText.className = 'status-text error';
            setTimeout(() => {
                statusText.textContent = '';
                statusText.className = 'status-text';
            }, 3000);
        }
    }

    shutdown() {
        apiClient.closeGameWs();
    }
}

// ============================================================================
// PHASER GAME CONFIGURATION
// ============================================================================

const config = {
    type: Phaser.AUTO,
    width: 1000,
    height: 720,
    parent: 'game-container',
    physics: {
        default: 'arcade',
        arcade: {
            gravity: { y: 0 },
            debug: false,
        },
    },
    scene: [LobbyScene, GameScene],
    scale: {
        mode: Phaser.Scale.FIT,
        autoCenter: Phaser.Scale.CENTER_BOTH,
    },
};

// Create game instance
const game = new Phaser.Game(config);
