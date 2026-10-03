import { useCallback, useEffect, useState } from "react";

export type AsyncState<T> =
  | { status: "loading"; data?: undefined; error?: undefined }
  | { status: "success"; data: T; error?: undefined }
  | { status: "error"; data?: undefined; error: Error };

type Settled<T> = Exclude<AsyncState<T>, { status: "loading" }>;

const LOADING = { status: "loading" } as const;

/**
 * Run an async loader and track loading / success / error.
 *
 * Re-runs whenever `key` or `loader` changes (memoise `loader` with
 * useCallback) and on `reload()`. A result is only shown for the request
 * that produced it, so fast switching between stops never shows stale data.
 * Pass `key = null` to stay idle.
 */
export function useAsync<T>(
  loader: () => Promise<T>,
  key: string | null,
): AsyncState<T> & { reload: () => void } {
  const [nonce, setNonce] = useState(0);
  const [result, setResult] = useState<{ tag: string; state: Settled<T> } | null>(null);
  const tag = `${key}#${nonce}`;

  useEffect(() => {
    if (key === null) return;
    let cancelled = false;
    loader().then(
      (data) => !cancelled && setResult({ tag, state: { status: "success", data } }),
      (error: unknown) =>
        !cancelled &&
        setResult({
          tag,
          state: {
            status: "error",
            error: error instanceof Error ? error : new Error(String(error)),
          },
        }),
    );
    return () => {
      cancelled = true;
    };
  }, [loader, key, tag]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  const state: AsyncState<T> = result && result.tag === tag ? result.state : LOADING;
  return { ...state, reload };
}
