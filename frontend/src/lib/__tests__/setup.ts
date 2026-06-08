import "@testing-library/jest-dom/vitest";

const localStorageStore: Record<string, string> = {};

if (typeof globalThis.localStorage === "undefined") {
  Object.defineProperty(globalThis, "localStorage", {
    value: {
      getItem: (key: string) => localStorageStore[key] ?? null,
      setItem: (key: string, value: string) => {
        localStorageStore[key] = value;
      },
      removeItem: (key: string) => {
        delete localStorageStore[key];
      },
      clear: () => {
        for (const key of Object.keys(localStorageStore)) {
          delete localStorageStore[key];
        }
      },
      get length() {
        return Object.keys(localStorageStore).length;
      },
      key: (index: number) => Object.keys(localStorageStore)[index] ?? null,
    },
    writable: true,
  });
}
