// The shapes the fixture Party server returns (server/party.mjs).
export type Member = { id: string; name: string; avatar: string; host: boolean; me: boolean };
export type Notice =
  | { id: string; kind: 'your_turn'; game: string; deadline: number }
  | { id: string; kind: 'top_suggestion'; game: string; by: string };
export type View = {
  version: number; me: Member; role: 'player' | 'spectator'; now: number;
  location: { at: 'game'; game: string }; attention: Notice[]; members: Member[];
};
export type Suggestion = { id: string; game: string; by: string; approvals: string[]; count: number };
export type Game = { id: string; name: string; players: { min: number; max: number }; screen: string; blurb: string };
export type Viewport = { type: 'viewport'; w: number; h: number; insets: { top: number; right: number; bottom: number; left: number } };
export type TabId = 'home' | 'party' | 'library' | 'me';
