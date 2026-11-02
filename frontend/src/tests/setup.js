// Node test environment setup: polyfill localStorage, sessionStorage, and env
if (typeof global.localStorage === "undefined") {
  const store = {};
  global.localStorage = {
    getItem: (key) => (key in store ? store[key] : null),
    setItem: (key, value) => {
      store[key] = String(value);
    },
    removeItem: (key) => {
      delete store[key];
    },
    clear: () => {
      Object.keys(store).forEach((key) => delete store[key]);
    },
  };
}

if (typeof global.sessionStorage === "undefined") {
  const sessionStore = {};
  global.sessionStorage = {
    getItem: (key) => (key in sessionStore ? sessionStore[key] : null),
    setItem: (key, value) => {
      sessionStore[key] = String(value);
    },
    removeItem: (key) => {
      delete sessionStore[key];
    },
    clear: () => {
      Object.keys(sessionStore).forEach((key) => delete sessionStore[key]);
    },
  };
}
