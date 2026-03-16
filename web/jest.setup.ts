import "@testing-library/jest-dom";
import { TextDecoder, TextEncoder } from "util";

Object.assign(global, {
  TextEncoder,
  TextDecoder,
});

class MockEventSource {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 2;

  url: string;
  withCredentials = false;
  readyState = MockEventSource.OPEN;
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;

  constructor(url: string) {
    this.url = url;
  }

  addEventListener() {}
  removeEventListener() {}
  dispatchEvent() {
    return true;
  }
  close() {
    this.readyState = MockEventSource.CLOSED;
  }
}

Object.defineProperty(global, "EventSource", {
  value: MockEventSource,
  writable: true,
  configurable: true,
});
