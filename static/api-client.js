/**
 * API Client for Basic Land Game
 * Handles REST and WebSocket communication with the server
 */

class GameAPIClient {
    constructor(baseUrl = 'http://localhost:8000') {
        this.baseUrl = baseUrl;
        this.wsBaseUrl = baseUrl.replace('http', 'ws');
        this.playerToken = null;
        this.playerId = null;
        this.lobbyWs = null;
        this.gameWs = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
    }

    // ========================================
    // Lobby API
    // ========================================

    async joinLobby(name) {
        const response = await fetch(`${this.baseUrl}/lobby/join`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name }),
        });
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.detail || 'Failed to join lobby');
        }
        this.playerToken = data.player_token;
        this.playerId = data.player_id;
        return data;
    }

    async getWaitingPlayers() {
        const response = await fetch(
            `${this.baseUrl}/lobby/waiting?player_token=${this.playerToken}`
        );
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.detail || 'Failed to get waiting players');
        }
        return data.waiting;
    }

    async challengeOpponent(opponentId) {
        const response = await fetch(`${this.baseUrl}/lobby/challenge?player_token=${this.playerToken}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ opponent_player_id: opponentId }),
        });
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.detail || 'Failed to challenge opponent');
        }
        return data;
    }

    async leaveLobby() {
        const response = await fetch(
            `${this.baseUrl}/lobby/leave?player_token=${this.playerToken}`,
            { method: 'DELETE' }
        );
        if (!response.ok) {
            const data = await response.json();
            throw new Error(data.detail || 'Failed to leave lobby');
        }
        return response.json();
    }

    // ========================================
    // Game API
    // ========================================

    async getGameState(gameId) {
        const response = await fetch(
            `${this.baseUrl}/games/${gameId}/state?player_token=${this.playerToken}`
        );
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.detail || 'Failed to get game state');
        }
        return data;
    }

    async submitAction(gameId, action) {
        const response = await fetch(
            `${this.baseUrl}/games/${gameId}/action?player_token=${this.playerToken}`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(action),
            }
        );
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.message || 'Failed to submit action');
        }
        return data;
    }

    // ========================================
    // WebSocket - Lobby
    // ========================================

    connectLobbyWs(onMessage, onError) {
        return new Promise((resolve, reject) => {
            const wsUrl = `${this.wsBaseUrl}/lobby/ws?player_token=${this.playerToken}`;
            this.lobbyWs = new WebSocket(wsUrl);

            this.lobbyWs.onopen = () => {
                console.log('Lobby WebSocket connected');
                this.reconnectAttempts = 0;
                resolve();
            };

            this.lobbyWs.onmessage = (event) => {
                const message = JSON.parse(event.data);
                onMessage(message);
            };

            this.lobbyWs.onerror = (error) => {
                console.error('Lobby WebSocket error:', error);
                onError(error);
                reject(error);
            };

            this.lobbyWs.onclose = () => {
                console.log('Lobby WebSocket closed');
            };
        });
    }

    sendLobbyPing() {
        if (this.lobbyWs && this.lobbyWs.readyState === WebSocket.OPEN) {
            this.lobbyWs.send('ping');
        }
    }

    closeLobbyWs() {
        if (this.lobbyWs) {
            this.lobbyWs.close();
            this.lobbyWs = null;
        }
    }

    // ========================================
    // WebSocket - Game
    // ========================================

    connectGameWs(gameId, onMessage, onError) {
        return new Promise((resolve, reject) => {
            const wsUrl = `${this.wsBaseUrl}/games/${gameId}/ws?player_token=${this.playerToken}`;
            this.gameWs = new WebSocket(wsUrl);

            this.gameWs.onopen = () => {
                console.log('Game WebSocket connected');
                this.reconnectAttempts = 0;
                resolve();
            };

            this.gameWs.onmessage = (event) => {
                const message = JSON.parse(event.data);
                onMessage(message);
            };

            this.gameWs.onerror = (error) => {
                console.error('Game WebSocket error:', error);
                onError(error);
                reject(error);
            };

            this.gameWs.onclose = () => {
                console.log('Game WebSocket closed');
            };
        });
    }

    submitActionViaWs(action) {
        if (this.gameWs && this.gameWs.readyState === WebSocket.OPEN) {
            this.gameWs.send(JSON.stringify(action));
        }
    }

    sendGamePing() {
        if (this.gameWs && this.gameWs.readyState === WebSocket.OPEN) {
            this.gameWs.send(JSON.stringify({ type: 'ping' }));
        }
    }

    closeGameWs() {
        if (this.gameWs) {
            this.gameWs.close();
            this.gameWs = null;
        }
    }

    // ========================================
    // Utility
    // ========================================

    isConnected() {
        return this.playerToken !== null;
    }

    getToken() {
        return this.playerToken;
    }
}

// Global API client instance
const apiClient = new GameAPIClient();
