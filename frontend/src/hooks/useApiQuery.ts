import { useCallback, useEffect, useState, type DependencyList } from "react";

import { ApiError } from "../api/client";

export type QueryState<T> =
  | { status: "loading"; data?: undefined; error?: undefined }
  | { status: "success"; data: T; error?: undefined }
  | { status: "error"; data?: undefined; error: ApiError };

/**
 * Run an api/ function and track its loading, success and error states.
 *
 * Refetches when `deps` change, aborts the request when the component unmounts or
 * `deps` change, and exposes `retry()` for error states. Server data stays in the
 * component that asked for it (docs/frontend.md, "State management").
 */
export function useApiQuery<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  deps: DependencyList,
): QueryState<T> & { retry: () => void } {
  const [state, setState] = useState<QueryState<T>>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: "loading" });

    fetcher(controller.signal).then(
      (data) => {
        if (!controller.signal.aborted) setState({ status: "success", data });
      },
      (err: unknown) => {
        if (controller.signal.aborted) return;
        const error =
          err instanceof ApiError
            ? err
            : new ApiError("unexpected_response", "Something went wrong loading this data.", null);
        setState({ status: "error", error });
      },
    );

    return () => controller.abort();
    // `fetcher` is usually an inline closure; callers list what it depends on in `deps`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, attempt]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  return { ...state, retry };
}
