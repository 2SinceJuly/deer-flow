import { afterEach, beforeEach, expect, rs, test } from "@rstest/core";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { createElement, type ReactNode } from "react";

import { I18nContext } from "@/core/i18n/context";
import { enUS } from "@/core/i18n/locales/en-US";
import { DEFAULT_LOCAL_SETTINGS } from "@/core/settings/local";

// A 5xx from the gateway surfaces through the SDK as
// `HTTPError("HTTP 502: {\"detail\":\"upstream failed\"}")`. The toast must not
// echo that body; it keeps only the status. 4xx and non-HTTP errors stay as-is.

const mocks = rs.hoisted(() => ({
  toastError: rs.fn(),
  submit: rs.fn(async () => undefined),
  streamOptions: null as null | Record<string, unknown>,
}));

rs.mock("sonner", () => ({
  toast: {
    error: mocks.toastError,
    success: rs.fn(),
    warning: rs.fn(),
  },
}));

rs.mock("@langchain/langgraph-sdk/react", () => ({
  useStream: (options: Record<string, unknown>) => {
    mocks.streamOptions = options;
    return {
      isLoading: false,
      messages: [],
      stop: rs.fn(async () => undefined),
      submit: mocks.submit,
      values: { artifacts: [], messages: [], title: "", todos: [] },
    };
  },
}));

function createWrapper() {
  return function StreamErrorTestWrapper({
    children,
  }: {
    children: ReactNode;
  }) {
    return createElement(
      QueryClientProvider,
      {
        client: new QueryClient({
          defaultOptions: { queries: { retry: false } },
        }),
      },
      createElement(
        I18nContext.Provider,
        {
          value: { locale: "en-US", setLocale: () => undefined, t: enUS },
        },
        children,
      ),
    );
  };
}

async function flushFrames() {
  for (let index = 0; index < 6; index += 1) {
    await act(async () => undefined);
  }
}

async function renderThreadStream() {
  const { useThreadStream } = await import("@/core/threads/hooks");
  const rendered = renderHook(
    () =>
      useThreadStream({
        context: DEFAULT_LOCAL_SETTINGS.context,
        isMock: false,
        threadId: "thread-1",
      }),
    { wrapper: createWrapper() },
  );
  await flushFrames();
  return rendered;
}

function emitStreamError(error: unknown) {
  const onError = mocks.streamOptions?.onError as
    | ((error: unknown, run: unknown) => void)
    | undefined;
  expect(typeof onError).toBe("function");
  act(() => {
    onError?.(error, undefined);
  });
}

function httpError(status: number, body: string) {
  const error = new Error(`HTTP ${status}: ${body}`);
  Object.assign(error, { status });
  return error;
}

function stubHistoryFetch() {
  rs.stubGlobal("fetch", async (input: unknown) => {
    const url = String(input);
    if (url.includes("/messages/page")) {
      return new Response(
        JSON.stringify({ data: [], has_more: false, next_before_seq: null }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }
    throw new Error(`Unexpected fetch: ${url}`);
  });
}

beforeEach(() => {
  mocks.toastError.mockReset();
  mocks.streamOptions = null;
  stubHistoryFetch();
});

afterEach(() => {
  rs.unstubAllGlobals();
});

test("does not echo the gateway body for a 5xx stream failure", async () => {
  await renderThreadStream();

  emitStreamError(httpError(502, '{"detail":"upstream failed"}'));

  expect(mocks.toastError).toHaveBeenCalledTimes(1);
  const shown = mocks.toastError.mock.calls[0]?.[0] as string;
  expect(shown).toBe(
    "Service temporarily unavailable (HTTP 502). Please try again later.",
  );
  expect(shown.includes("upstream failed")).toBe(false);
  expect(shown.includes("502:")).toBe(false);
});

test("applies the same 5xx copy to every server status", async () => {
  await renderThreadStream();

  emitStreamError(httpError(500, '{"detail":"internal trace"}'));

  const shown = mocks.toastError.mock.calls[0]?.[0] as string;
  expect(shown).toBe(
    "Service temporarily unavailable (HTTP 500). Please try again later.",
  );
  expect(shown.includes("internal trace")).toBe(false);
});

test("keeps 4xx SDK messages verbatim", async () => {
  await renderThreadStream();

  emitStreamError(httpError(409, '{"detail":"run already finished"}'));

  expect(mocks.toastError.mock.calls[0]?.[0]).toBe(
    'HTTP 409: {"detail":"run already finished"}',
  );
});

test("keeps non-HTTP errors verbatim", async () => {
  await renderThreadStream();

  emitStreamError(new Error("network request failed"));

  expect(mocks.toastError.mock.calls[0]?.[0]).toBe("network request failed");
});

test("falls back to the localized text when the error carries no message", async () => {
  await renderThreadStream();

  emitStreamError(Object.create(null));

  expect(mocks.toastError.mock.calls[0]?.[0]).toBe("Request failed.");
});
