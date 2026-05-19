// Bridge RankForge agents to the running Agent Mesh broker.
//
// Each RankForge agent registers as a mesh instance, so the human-facing UI
// at http://localhost:8765 shows them alongside any Claude Code clients, and
// agents can pub/sub messages to each other through the broker we already
// built. This file is a thin wrapper over the WS+REST protocol.
//
// Falls back to a stub when MESH_BROKER_URL is unset — so unit tests run
// without a live broker.

const BROKER_HTTP = process.env.MESH_BROKER_URL ?? "http://localhost:8765";
const BROKER_WS = (process.env.MESH_BROKER_WS_URL
    ?? BROKER_HTTP.replace(/^http/, "ws").replace(/:\d+$/, ":8766"));
const MESH_TOKEN = process.env.MESH_TOKEN || null;
const MESH_DISABLED = process.env.MESH_DISABLED === "1" || !process.env.MESH_BROKER_URL;

export interface MeshIncomingMessage {
    type: string;
    from?: string;
    to?: string;
    text?: string;
    payload?: unknown;
    [key: string]: unknown;
}

export type MeshHandler = (msg: MeshIncomingMessage) => void;

class MeshClient {
    private ws: WebSocket | null = null;
    private handlers: MeshHandler[] = [];
    private connected = false;
    private reconnectDelay = 1000;
    private stopped = false;
    private id: string;
    private name: string;

    constructor(id: string, name: string) {
        this.id = id;
        this.name = name;
        if (!MESH_DISABLED) this.connect();
    }

    private connect(): void {
        if (this.stopped) return;
        try {
            // Node 22+ and browsers have a global WebSocket.
            this.ws = new WebSocket(BROKER_WS);
        } catch (e) {
            // Bridge disabled silently if the runtime can't even instantiate.
            return;
        }
        this.ws.addEventListener("open", () => {
            const reg: Record<string, unknown> = {
                type: "register",
                id: this.id,
                name: this.name,
                project: "rankforge",
            };
            if (MESH_TOKEN) reg.token = MESH_TOKEN;
            this.ws!.send(JSON.stringify(reg));
            this.connected = true;
            this.reconnectDelay = 1000;
        });
        this.ws.addEventListener("message", (ev) => {
            let parsed: MeshIncomingMessage;
            try {
                parsed = JSON.parse(typeof ev.data === "string" ? ev.data : "");
            } catch {
                return;
            }
            for (const h of this.handlers) {
                try {
                    h(parsed);
                } catch {
                    // never let a handler crash the loop
                }
            }
        });
        this.ws.addEventListener("close", () => {
            this.connected = false;
            this.ws = null;
            if (this.stopped) return;
            setTimeout(() => this.connect(), this.reconnectDelay);
            this.reconnectDelay = Math.min(this.reconnectDelay * 2, 30_000);
        });
        this.ws.addEventListener("error", () => {
            // close event fires after error; reconnect handled there
        });
    }

    on(handler: MeshHandler): void {
        this.handlers.push(handler);
    }

    async send(to: string, text: string): Promise<void> {
        if (MESH_DISABLED) return;
        // One-shot REST POST is more reliable than waiting for WS readiness.
        try {
            await fetch(`${BROKER_HTTP}/api/send`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    ...(MESH_TOKEN ? { "X-Mesh-Token": MESH_TOKEN } : {}),
                },
                body: JSON.stringify({ to, text, from: this.id }),
            });
        } catch {
            // bridge is best-effort; never fail an agent run because the
            // mesh is down.
        }
    }

    async broadcast(text: string): Promise<void> {
        return this.send("all", text);
    }

    async status(task: string, workload = 0): Promise<void> {
        if (MESH_DISABLED || !this.ws || !this.connected) return;
        try {
            this.ws.send(JSON.stringify({ type: "status", task, workload }));
        } catch {
            // ignore
        }
    }

    async log(text: string, level: "info" | "warn" | "error" | "debug" = "info"): Promise<void> {
        if (MESH_DISABLED || !this.ws || !this.connected) return;
        try {
            this.ws.send(JSON.stringify({ type: "log", text, level }));
        } catch {
            // ignore
        }
    }

    stop(): void {
        this.stopped = true;
        try {
            this.ws?.close();
        } catch {
            // ignore
        }
    }
}

// One mesh client per process. Agents share it.
let _mesh: MeshClient | null = null;

export function getMesh(id = "rankforge", name = "RankForge"): MeshClient {
    if (_mesh === null) _mesh = new MeshClient(id, name);
    return _mesh;
}

export function meshEnabled(): boolean {
    return !MESH_DISABLED;
}
