export async function onRequestError(
  err: { digest: string; message: string },
  request: { path: string; method: string },
) {
  console.error(
    `[next-ssr-error] ${request.method} ${request.path} → ${err.message} (digest: ${err.digest})`,
  );
}
