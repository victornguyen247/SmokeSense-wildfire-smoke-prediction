// The typed API client. Every request to the backend goes through `apiClient`, and
// every response through `unwrap`, so base URL, error shape and network failures are
// handled in one place (docs/frontend.md, "api/").

import createClient from "openapi-fetch";

import { API_BASE_URL } from "../constants/env";
import type { ApiErrorBody, Bbox } from "./models";
import type { paths } from "./types";

export const apiClient = createClient<paths>({ baseUrl: API_BASE_URL });

/**
 * A failed API call. `code` is the API's stable error code (docs/api.md, "Errors"),
 * or `network_error` / `unexpected_response` when no valid error body came back.
 * `message` is safe to show to people.
 */
export class ApiError extends Error {
  readonly code: ApiErrorBody["code"] | "network_error" | "unexpected_response";
  readonly status: number | null;

  constructor(code: ApiError["code"], message: string, status: number | null) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }
}

function isErrorBody(value: unknown): value is ApiErrorBody {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as ApiErrorBody).code === "string" &&
    typeof (value as ApiErrorBody).message === "string"
  );
}

/** Resolve an `apiClient` call to its data, or throw an `ApiError`. */
export async function unwrap<T>(
  call: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  let result: Awaited<typeof call>;
  try {
    result = await call;
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError(
      "network_error",
      "Couldn't reach the SmokeSense API. Check your connection and try again.",
      null,
    );
  }

  const { data, error, response } = result;
  if (response.ok && data !== undefined) return data;
  if (isErrorBody(error)) throw new ApiError(error.code, error.message, response.status);
  throw new ApiError(
    "unexpected_response",
    `The API sent an unexpected response (HTTP ${response.status}).`,
    response.status,
  );
}

/** Format a bbox for the `bbox` query parameter, or omit it to mean all of California. */
export function bboxParam(bbox?: Bbox): { bbox?: string } {
  return bbox ? { bbox: bbox.join(",") } : {};
}
