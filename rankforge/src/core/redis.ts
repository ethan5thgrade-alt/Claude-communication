// Minimal Redis-like KV store. Backed by Upstash/Redis if REDIS_URL set,
// in-memory otherwise. Surface = just the operations RankForge actually needs:
// get/set/del/incr/expire + a tiny sliding-window counter for rate limits.

export interface KV {
    get<T = unknown>(key: string): Promise<T | null>;
    set(key: string, value: unknown, ttlSeconds?: number): Promise<void>;
    del(key: string): Promise<void>;
    incr(key: string, by?: number): Promise<number>;
    expire(key: string, ttlSeconds: number): Promise<void>;
    /** Sliding-window: how many events in the last `windowSeconds`? */
    slidingCount(key: string, windowSeconds: number): Promise<number>;
    /** Record an event in the sliding window. */
    slidingHit(key: string, windowSeconds: number): Promise<number>;
    /** Acquire a lock that auto-expires. Returns true if acquired. */
    lockAcquire(key: string, ttlSeconds: number): Promise<boolean>;
    lockRelease(key: string): Promise<void>;
}

interface Entry { value: unknown; expiresAt: number | null }

class InMemoryKV implements KV {
    private map = new Map<string, Entry>();
    private sliding = new Map<string, number[]>();

    private isExpired(e: Entry): boolean {
        return e.expiresAt !== null && Date.now() > e.expiresAt;
    }

    async get<T = unknown>(key: string): Promise<T | null> {
        const e = this.map.get(key);
        if (!e) return null;
        if (this.isExpired(e)) {
            this.map.delete(key);
            return null;
        }
        return e.value as T;
    }

    async set(key: string, value: unknown, ttlSeconds?: number): Promise<void> {
        this.map.set(key, {
            value,
            expiresAt: ttlSeconds ? Date.now() + ttlSeconds * 1000 : null,
        });
    }

    async del(key: string): Promise<void> {
        this.map.delete(key);
    }

    async incr(key: string, by: number = 1): Promise<number> {
        const cur = await this.get<number>(key);
        const next = (cur ?? 0) + by;
        await this.set(key, next);
        return next;
    }

    async expire(key: string, ttlSeconds: number): Promise<void> {
        const e = this.map.get(key);
        if (e) e.expiresAt = Date.now() + ttlSeconds * 1000;
    }

    async slidingCount(key: string, windowSeconds: number): Promise<number> {
        const events = this.sliding.get(key) ?? [];
        const cutoff = Date.now() - windowSeconds * 1000;
        const live = events.filter(t => t > cutoff);
        this.sliding.set(key, live);
        return live.length;
    }

    async slidingHit(key: string, windowSeconds: number): Promise<number> {
        const events = this.sliding.get(key) ?? [];
        const cutoff = Date.now() - windowSeconds * 1000;
        const live = events.filter(t => t > cutoff);
        live.push(Date.now());
        this.sliding.set(key, live);
        return live.length;
    }

    async lockAcquire(key: string, ttlSeconds: number): Promise<boolean> {
        const existing = this.map.get(key);
        if (existing && !this.isExpired(existing)) return false;
        await this.set(`lock:${key}`, true, ttlSeconds);
        await this.set(key, true, ttlSeconds);
        return true;
    }

    async lockRelease(key: string): Promise<void> {
        await this.del(`lock:${key}`);
        await this.del(key);
    }
}

export function makeKV(): KV {
    const url = process.env.REDIS_URL;
    if (!url) return new InMemoryKV();
    // TODO: real Redis adapter (ioredis / upstash) when REDIS_URL is set.
    return new InMemoryKV();
}

export const kv: KV = makeKV();
