import { useEffect, useEffectEvent } from "react";
import { wsUrl } from "../api";

const FIRST_RETRY_MS = 1000;
const MAX_RETRY_MS = 10000;

type Handlers = {
  onOpen?: () => void;
  /** `close` drops this connection (for example on a malformed message); it then reconnects. */
  onMessage: (event: MessageEvent, close: () => void) => void;
  /** Called on every unexpected close, before the reconnect is scheduled. */
  onClose?: () => void;
  /** Reconnects when no message arrives this long after opening or after the last message. */
  idleTimeoutMs?: number;
};

/**
 * Keeps a WebSocket to an API path open: reconnects with exponential backoff (1 s up to 10 s,
 * reset by the first message) and closes cleanly when the component unmounts or `path` changes.
 * Handlers always see the latest props without reopening the socket.
 */
export function useReconnectingWebSocket(path: string, handlers: Handlers) {
  const onOpen = useEffectEvent(() => handlers.onOpen?.());
  const onMessage = useEffectEvent((event: MessageEvent, close: () => void) =>
    handlers.onMessage(event, close),
  );
  const onClose = useEffectEvent(() => handlers.onClose?.());
  const { idleTimeoutMs } = handlers;

  useEffect(() => {
    let stopped = false;
    let retryTimer: number | undefined;
    let idleTimer: number | undefined;
    let retryDelay = FIRST_RETRY_MS;
    let socket: WebSocket;

    const watchIdle = () => {
      if (idleTimeoutMs === undefined) return;
      window.clearTimeout(idleTimer);
      idleTimer = window.setTimeout(() => socket.close(), idleTimeoutMs);
    };
    const connect = () => {
      socket = new WebSocket(wsUrl(path));
      socket.onopen = () => {
        watchIdle();
        onOpen();
      };
      socket.onmessage = (event: MessageEvent) => {
        retryDelay = FIRST_RETRY_MS;
        watchIdle();
        onMessage(event, () => socket.close());
      };
      socket.onerror = () => socket.close();
      socket.onclose = () => {
        window.clearTimeout(idleTimer);
        if (stopped) return;
        onClose();
        retryTimer = window.setTimeout(connect, retryDelay);
        retryDelay = Math.min(retryDelay * 2, MAX_RETRY_MS);
      };
    };
    connect();
    return () => {
      stopped = true;
      window.clearTimeout(retryTimer);
      window.clearTimeout(idleTimer);
      socket.onopen = socket.onmessage = socket.onerror = socket.onclose = null;
      socket.close();
    };
  }, [path, idleTimeoutMs]);
}
