import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "../api/client";

export type QueryState<T> =
  | { status: "loading"; data?: undefined; error?: undefined }
  | { status: "success"; data: T; error?: undefined }
  | { status: "error"; data?: undefined; error: ApiError };

type Settled<T> = Exclude<QueryState<T>, { status: "loading" }>;

function toApiError(err: unknown): ApiError {
  return err instanceof ApiError
    ? err
    : new ApiError("unexpected_response", "Something went wrong loading this data.", null);
}

/**
 * Run an api/ function and track its loading, success and error states.
 *
 * `key` identifies the request: the query refetches whenever it changes, so build it from
 * every input the fetcher uses (e.g. `forecast-point:${lat},${lon}`). The request is
 * aborted when the component unmounts or the key changes, and `retry()` refetches after
 * an error. Server data stays in the component that asked for it (docs/frontend.md,
 * "State management").
 */
export function useApiQuery<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  key: string,
): QueryState<T> & { retry: () => void } {
  const [attempt, setAttempt] = useState(0);
  const requestKey = `${key}#${attempt}`;
  const [settled, setSettled] = useState<{ key: string; state: Settled<T> } | null>(null);

  // Always call the latest fetcher without making it an effect dependency: callers
  // usually pass an inline closure, and `key` already says when to refetch.
  const fetcherRef = useRef(fetcher);
  useEffect(() => {
    fetcherRef.current = fetcher;
  });

  useEffect(() => {
    const controller = new AbortController();
    fetcherRef.current(controller.signal).then(
      (data) => {
        if (!controller.signal.aborted) {
          setSettled({ key: requestKey, state: { status: "success", data } });
        }
      },
      (err: unknown) => {
        if (!controller.signal.aborted) {
          setSettled({ key: requestKey, state: { status: "error", error: toApiError(err) } });
        }
      },
    );
    return () => controller.abort();
  }, [requestKey]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);

  // Until the current request settles, report loading rather than the previous result.
  const state: QueryState<T> =
    settled?.key === requestKey ? settled.state : { status: "loading" };
  return { ...state, retry };
}
