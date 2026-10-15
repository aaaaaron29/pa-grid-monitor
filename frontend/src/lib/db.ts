import postgres from "postgres";

// Singleton connection, reused across requests in the same server process (Node.js
// runtime only -- see ARCHITECTURE.md Section 9 item 7). In production this should be
// Neon's POOLED connection string (the "-pooler" host); the direct/unpooled string is
// only for one-off migration commands, not this app.
const globalForSql = globalThis as unknown as { sql?: ReturnType<typeof postgres> };

export const sql =
  globalForSql.sql ??
  postgres(process.env.DATABASE_URL!, {
    ssl: process.env.DATABASE_URL?.includes("localhost") ? false : "require",
    idle_timeout: 20,
    max_lifetime: 60 * 30,
  });

if (process.env.NODE_ENV !== "production") {
  globalForSql.sql = sql;
}
