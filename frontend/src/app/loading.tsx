export default function Loading() {
  return (
    <div className="min-h-[calc(100vh-3.5rem)] flex flex-col items-center justify-center">
      <div className="h-10 w-10 animate-spin rounded-full border-4 border-zinc-700 border-t-zinc-400" />
      <p className="mt-4 text-sm text-zinc-400">Loading...</p>
    </div>
  );
}
