/**
 * Agent Mesh — TypeScript client.
 *
 * Mirrors the helper surface of `connect.py` so Node 22+/Bun-based Claude
 * Code instances (or external scripts) can join the mesh without a Python
 * runtime.
 *
 * Zero runtime deps — uses the global `WebSocket` available in Node 22+,
 * Bun, Deno, and browsers. For Node <22 install the `ws` package and pass
 * an explicit constructor via `options.websocketImpl`.
 */

// ---------------- types ----------------

export interface MeshMessage {
  id?: string;
  from: string;
  to: string;
  text: string;
  ts?: string;
}

export interface MeshTask {
  id: string;
  title: string;
  assignee: string;
  priority: string;
  deps: string[];
  status: string;
  created_by: string;
  ts: string;
  result?: string;
  done_by?: string;
  done_at?: string;
}

export interface MeshMemory {
  id: string;
  key: string;
  value: unknown;
  type: string;
  by: string;
  ts: string;
}

export interface MeshApproval {
  id: string;
  from: string;
  action: string;
  risk: string;
  detail: string;
  status: string;
  ts: string;
}

// Discriminated union of every event the broker can push to an instance.
export type IncomingEvent =
  | { type: "message"; id?: string; from: string; to: string; text: string; ts?: string }
  | { type: "memory_write"; memory: MeshMemory }
  | { type: "memory_init"; memory: MeshMemory[]; ts: string }
  | { type: "tasks_init"; tasks: MeshTask[]; ts: string }
  | { type: "task_assigned"; task: MeshTask }
  | { type: "task_completed"; task: MeshTask }
  | { type: "backlog"; messages: IncomingEvent[] }
  | { type: "approval_decision"; id: string; action: string; decision: boolean }
  | { type: "approval_request"; approval: MeshApproval }
  | { type: "control"; paused: boolean }
  | { type: "error"; error: string; ref?: string }
  | { type: string; [k: string]: unknown };

export type EventType = IncomingEvent["type"];
export type EventHandler<E extends IncomingEvent = IncomingEvent> = (event: E) => void;

export interface ConnectOptions {
  id: string;
  name: string;
  project: string;
  brokerUrl?: string;
  token?: string;
  /** Override the WebSocket implementation (useful on Node <22 with the `ws` package). */
  websocketImpl?: typeof WebSocket;
  /** Suppress the built-in `[CONNECTED] / [DISCONNECTED]` logging. */
  quiet?: boolean;
}

// ---------------- client ----------------

const DEFAULT_BROKER = "ws://localhost:8766";

export class MeshClient {
  readonly id: string;
  readonly name: string;
  readonly project: string;
  readonly brokerUrl: string;
  readonly token?: string;

  private ws: WebSocket | null = null;
  private handlers = new Map<string, Set<EventHandler>>();
  private wildcardHandlers = new Set<EventHandler>();
  private wsImpl: typeof WebSocket;
  private quiet: boolean;

  private reconnectDelay = 1.0;
  private stopped = false;
  private connectedOnce = false;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(opts: ConnectOptions) {
    this.id = opts.id;
    this.name = opts.name;
    this.project = opts.project;
    this.brokerUrl = opts.brokerUrl ?? DEFAULT_BROKER;
    this.token = opts.token;
    this.quiet = opts.quiet ?? false;

    const impl = opts.websocketImpl ?? (globalThis as { WebSocket?: typeof WebSocket }).WebSocket;
    if (!impl) {
      throw new Error(
        "No WebSocket implementation found. Use Node 22+, Bun, Deno, a browser, " +
          "or pass `websocketImpl` (e.g. `import WebSocket from 'ws'`).",
      );
    }
    this.wsImpl = impl;
  }

  // --------- lifecycle ---------

  /** Open the socket. Resolves after the first `register` payload has been
   *  flushed (i.e. the broker is aware of us). */
  async start(): Promise<void> {
    this.stopped = false;
    await this._openOnce();
  }

  /** Permanently close — no further reconnect attempts. */
  disconnect(): void {
    this.stopped = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      try {
        this.ws.close();
      } catch {
        /* noop */
      }
      this.ws = null;
    }
  }

  private _openOnce(): Promise<void> {
    return new Promise((resolve, reject) => {
      let settled = false;
      let ws: WebSocket;
      try {
        ws = new this.wsImpl(this.brokerUrl);
      } catch (err) {
        this._scheduleReconnect();
        reject(err);
        return;
      }
      this.ws = ws;

      ws.addEventListener("open", () => {
        const registerPayload: Record<string, unknown> = {
          type: "register",
          id: this.id,
          name: this.name,
          project: this.project,
        };
        if (this.token) registerPayload.token = this.token;
        try {
          ws.send(JSON.stringify(registerPayload));
          if (!this.quiet) {
            // eslint-disable-next-line no-console
            console.log(`[CONNECTED] ${this.id} -> ${this.brokerUrl}`);
          }
          this.reconnectDelay = 1.0;
          this.connectedOnce = true;
          if (!settled) {
            settled = true;
            resolve();
          }
        } catch (err) {
          if (!settled) {
            settled = true;
            reject(err);
          }
        }
      });

      ws.addEventListener("message", (evt: MessageEvent) => {
        const raw = typeof evt.data === "string" ? evt.data : evt.data?.toString?.();
        if (!raw) return;
        let payload: IncomingEvent;
        try {
          payload = JSON.parse(raw) as IncomingEvent;
        } catch {
          return;
        }
        this._dispatch(payload);
      });

      ws.addEventListener("error", () => {
        // The `close` handler runs after `error`; rely on it for reconnect.
      });

      ws.addEventListener("close", () => {
        this.ws = null;
        if (!this.quiet) {
          // eslint-disable-next-line no-console
          console.log(`[DISCONNECTED] retry in ${this.reconnectDelay.toFixed(1)}s`);
        }
        if (!settled) {
          settled = true;
          // First-attempt failure: still schedule reconnect but surface error.
          this._scheduleReconnect();
          reject(new Error("WebSocket closed before register completed"));
          return;
        }
        if (!this.stopped) {
          this._scheduleReconnect();
        }
      });
    });
  }

  private _scheduleReconnect(): void {
    if (this.stopped) return;
    if (this.reconnectTimer) return;
    const delayMs = Math.floor(this.reconnectDelay * 1000);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this._openOnce().catch(() => {
        /* swallowed; close handler will reschedule */
      });
    }, delayMs);
    this.reconnectDelay = Math.min(this.reconnectDelay * 2, 30.0);
  }

  private _dispatch(payload: IncomingEvent): void {
    const t = payload.type;
    const set = this.handlers.get(t);
    if (set) {
      for (const h of set) {
        try {
          h(payload);
        } catch (err) {
          // eslint-disable-next-line no-console
          console.error(`[handler error type=${t}]`, err);
        }
      }
    }
    for (const h of this.wildcardHandlers) {
      try {
        h(payload);
      } catch (err) {
        // eslint-disable-next-line no-console
        console.error(`[wildcard handler error type=${t}]`, err);
      }
    }
  }

  // --------- subscriptions ---------

  /**
   * Register an event handler.
   *
   *   client.on("message", e => console.log(e.from, e.text));
   *   client.on("*", e => log(e));   // catch-all
   *
   * Returns an unsubscribe function.
   */
  on<T extends EventType>(
    eventType: T,
    handler: EventHandler<Extract<IncomingEvent, { type: T }>>,
  ): () => void;
  on(eventType: "*", handler: EventHandler): () => void;
  on(eventType: string, handler: EventHandler): () => void {
    if (eventType === "*") {
      this.wildcardHandlers.add(handler);
      return () => this.wildcardHandlers.delete(handler);
    }
    let set = this.handlers.get(eventType);
    if (!set) {
      set = new Set();
      this.handlers.set(eventType, set);
    }
    set.add(handler);
    return () => set!.delete(handler);
  }

  // --------- outgoing helpers (mirror connect.py) ---------

  private _sendJson(payload: Record<string, unknown>): void {
    const ws = this.ws;
    if (!ws || ws.readyState !== 1 /* OPEN */) {
      if (!this.quiet) {
        // eslint-disable-next-line no-console
        console.log("[SKIP] not connected");
      }
      return;
    }
    try {
      ws.send(JSON.stringify(payload));
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error("[SEND ERROR]", err);
    }
  }

  send(text: string, to: string = "you"): void {
    this._sendJson({ type: "message", to, text });
  }

  broadcast(text: string): void {
    this._sendJson({ type: "broadcast", text });
  }

  status(task: string, workload: number = 0): void {
    this._sendJson({ type: "status", task, workload });
  }

  memory(key: string, value: unknown, memType: string = "contract"): void {
    this._sendJson({ type: "memory_write", key, value, mem_type: memType });
  }

  approveRequest(action: string, risk: string = "low", detail: string = ""): void {
    this._sendJson({ type: "approval_request", action, risk, detail });
  }

  typing(value: boolean = true): void {
    this._sendJson({ type: "typing", value: Boolean(value) });
  }

  taskCreate(
    title: string,
    assignee: string = "",
    priority: string = "normal",
    deps: string[] = [],
  ): void {
    this._sendJson({
      type: "task_create",
      title,
      assignee,
      priority,
      deps: [...deps],
    });
  }

  taskClaim(id: string): void {
    this._sendJson({ type: "task_claim", id });
  }

  taskStatus(id: string, status: string): void {
    this._sendJson({ type: "task_status", id, status });
  }

  taskDone(id: string, result: string = ""): void {
    this._sendJson({ type: "task_done", id, result });
  }

  // --------- introspection ---------

  get connected(): boolean {
    return this.ws !== null && this.ws.readyState === 1;
  }

  get everConnected(): boolean {
    return this.connectedOnce;
  }
}

/**
 * Convenience: instantiate, open, and return a ready `MeshClient`.
 *
 * ```ts
 * const mesh = await connectMesh({ id: "cc7", name: "TS Bot", project: "OPTFINDER" });
 * mesh.on("message", e => console.log(`[${e.from}] ${e.text}`));
 * mesh.send("Hello from TypeScript");
 * ```
 */
export async function connectMesh(opts: ConnectOptions): Promise<MeshClient> {
  const client = new MeshClient(opts);
  await client.start();
  return client;
}

export default connectMesh;
