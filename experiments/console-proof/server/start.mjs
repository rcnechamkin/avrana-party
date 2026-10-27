// Start the fixture Party origin, the fixture game origin and (for WebKit) the name-mapping proxy.
//   node server/start.mjs            Party :8370, game :8371, proxy :8372 (127.0.0.1 only)
import { createGameServer } from './game.mjs';
import { createPartyServer } from './party.mjs';
import { startProxy } from './proxy.mjs';
import { GAME_PORT, PARTY_PORT, PROXY_PORT } from './shared.mjs';

const game = createGameServer();
const party = createPartyServer(game);
game.server.listen(GAME_PORT, '127.0.0.1');
party.server.listen(PARTY_PORT, '127.0.0.1', () => console.log(`party :${PARTY_PORT} game :${GAME_PORT} proxy :${PROXY_PORT}`));
startProxy(PROXY_PORT);
