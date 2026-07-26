/**
 * A tiny cross-component pub/sub bus: "some session (ace-web legacy OR
 * canopy-hosted) changed — anyone showing a session list/title should
 * refetch." Used by `useCanopySessionsList`, `CanopyChatPanel`,
 * `ChatPage.tsx`'s `CanopyChatRoutePage`, and `RecentSessionsSidebar`.
 *
 * The `useRecentSessions()` hook that used to live alongside this (fetching
 * ace-web's own `listSessions`) was retired with the rest of the legacy chat
 * sidebar list — see the PR that deleted `useSessionSocket`/`sessionReducer`
 * and the "Legacy" section of `RecentSessionsSidebar`.
 */
export const SESSIONS_UPDATED_EVENT = "ace:sessions-updated";

export function notifySessionsUpdated() {
  window.dispatchEvent(new CustomEvent(SESSIONS_UPDATED_EVENT));
}
