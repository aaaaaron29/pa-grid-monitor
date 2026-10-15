import postgres from "postgres";

// Singleton connection, reused across requests in the same server process (Node.js
// runtime only -- see ARCHITECTURE.md Section 9 item 7). In production this should be
// Neon's POOLED connection string (the "-pooler" host); the direct/unpooled string is
// only for one-off migration commands, not this app.
const globalForSql = globalThis as unknown as { sql?: ReturnType<typeof postgres> };

const url = process.env.DATABASE_URL!;
// Neon's pooled endpoint sits behind PgBouncer in transaction mode, which can reject the named
// prepared statements postgres.js uses by default. Turn them off for pooled URLs only; a local
// or direct connection keeps them.
const isPooled = url?.includes("-pooler") ?? false;

export const sql =
  globalForSql.sql ??
  postgres(url, {
    ssl: url?.includes("localhost") ? false : "require",
    prepare: !isPooled,
    idle_timeout: 20,
    max_lifetime: 60 * 30,
  });

if (process.env.NODE_ENV !== "production") {
  globalForSql.sql = sql;
}
