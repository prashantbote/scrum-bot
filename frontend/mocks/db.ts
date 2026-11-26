import { createSeed, DB_VERSION, type MockDb } from "./data/seed";
import { storyFriday } from "./data/clock";

const KEY = "scrumbot.mockdb";

let db: MockDb | null = null;

function storage(): Storage | null {
  try {
    return typeof window !== "undefined" ? window.localStorage : null;
  } catch {
    return null;
  }
}

/** Lazily load the mock DB: from localStorage when it matches the current seed, else a fresh seed. */
export function getDb(): MockDb {
  if (db) return db;
  const store = storage();
  try {
    const raw = store?.getItem(KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as MockDb;
      if (parsed.version === DB_VERSION && parsed.storyFriday === storyFriday()) {
        db = parsed;
        return db;
      }
    }
  } catch {
    /* corrupted or blocked storage: fall through to a fresh seed */
  }
  db = createSeed();
  return db;
}

export function persist() {
  try {
    storage()?.setItem(KEY, JSON.stringify(db));
  } catch {
    /* quota / private mode: demo still works in memory */
  }
}

export function resetDb() {
  db = createSeed();
  try {
    storage()?.removeItem(KEY);
  } catch {
    /* ignore */
  }
}
