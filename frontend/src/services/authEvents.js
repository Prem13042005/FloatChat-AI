/**
 * FloatChat Authentication Event Bus
 *
 * Centralized, decoupled event mechanism allowing network interceptors
 * (Axios) to notify authentication contexts (AuthContext) of session
 * invalidation (e.g., HTTP 401) without introducing circular imports
 * or direct React state manipulation from interceptors.
 */

export const AUTH_EVENTS = Object.freeze({
  UNAUTHORIZED: "AUTH_UNAUTHORIZED",
});

const listeners = new Set();
let lastUnauthorizedTimestamp = 0;
const DEDUPLICATION_WINDOW_MS = 500;

/**
 * Register a listener for authentication events.
 *
 * @param {Function} callback - Event listener callback receiving { type, status, url }
 * @returns {Function} Unsubscribe function to cleanly remove the listener
 */
export function subscribeAuthEvent(callback) {
  if (typeof callback !== "function") return () => {};
  listeners.add(callback);
  return () => {
    listeners.delete(callback);
  };
}

/**
 * Dispatch an authentication event to all active listeners.
 * Throttles/deduplicates rapid consecutive UNAUTHORIZED events to prevent
 * duplicate logouts or redirect loops.
 *
 * @param {Object} event - Event descriptor
 * @returns {boolean} True if dispatched, false if throttled or invalid
 */
export function emitAuthEvent(event) {
  if (!event || typeof event !== "object") return false;

  if (event.type === AUTH_EVENTS.UNAUTHORIZED) {
    const now = Date.now();
    if (now - lastUnauthorizedTimestamp < DEDUPLICATION_WINDOW_MS) {
      // Deduplicate simultaneous 401 responses
      return false;
    }
    lastUnauthorizedTimestamp = now;
  }

  listeners.forEach((listener) => {
    try {
      listener(event);
    } catch (err) {
      console.error("Error in auth event listener:", err);
    }
  });

  return true;
}

/**
 * Test helper to reset registered listeners and rate-limiting timestamp
 */
export function _resetAuthEvents() {
  listeners.clear();
  lastUnauthorizedTimestamp = 0;
}

