from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections import OrderedDict
from uuid import uuid4

from utils.ai_provider import AIProvider

log = logging.getLogger(__name__)


class BatchEmbedder:
    """
    Shared embedding queue that coalesces requests across concurrent ingest jobs.

    Two flush triggers (whichever comes first):
      - queue reaches max_batch_size
      - window_ms milliseconds pass since first item was enqueued

    Content-hash LRU cache avoids re-embedding identical text across jobs or re-ingests.
    """

    def __init__(
        self,
        provider: AIProvider,
        max_batch_size: int,
        window_ms: float,
        cache_size: int,
    ) -> None:
        self._provider = provider
        self._max_batch = max_batch_size
        self._window_s = window_ms / 1000.0
        self._cache_size = cache_size
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        # pending: list of (content_hash, text, future)
        self._pending: list[tuple[str, str, asyncio.Future]] = []
        self._flush_task: asyncio.Task | None = None
        # Lazy: created on first use so __init__ needs no running event loop
        self._lock: asyncio.Lock | None = None

        # Observability counters — readable via stats()
        self._total_requests: int = 0
        self._cache_hits: int = 0
        self._flush_count: int = 0
        self._provider_errors: int = 0
        self._futures_orphaned: int = 0  # futures set_exception due to provider error

        log.info(
            "BatchEmbedder init provider=%s max_batch=%d window_ms=%g cache_size=%d",
            type(provider).__name__,
            max_batch_size,
            window_ms,
            cache_size,
        )

    # ── public API ────────────────────────────────────────────────────────────

    async def embed_one(self, text: str) -> list[float]:
        """Embed a single text, using cache or shared batch."""
        self._total_requests += 1
        key = hashlib.sha256(text.encode()).hexdigest()
        key_prefix = key[:8]  # short prefix for log tracing

        cached = self._cache_get(key)
        if cached is not None:
            self._cache_hits += 1
            log.debug("embed_one cache_hit key=%s text_len=%d", key_prefix, len(text))
            return cached

        log.debug("embed_one cache_miss key=%s text_len=%d", key_prefix, len(text))

        future: asyncio.Future[list[float]] = asyncio.get_running_loop().create_future()
        async with self._get_lock():
            self._pending.append((key, text, future))
            queue_depth = len(self._pending)
            log.debug(
                "embed_one enqueued key=%s queue_depth=%d max_batch=%d",
                key_prefix, queue_depth, self._max_batch,
            )

            if queue_depth >= self._max_batch:
                log.debug(
                    "embed_one batch_full queue_depth=%d trigger=size_limit",
                    queue_depth,
                )
                await self._flush(trigger="size_limit")
            elif self._flush_task is None or self._flush_task.done():
                log.debug(
                    "embed_one scheduling delayed_flush window_ms=%g",
                    self._window_s * 1000,
                )
                self._flush_task = asyncio.create_task(
                    self._delayed_flush(),
                    name=f"batch-embedder-flush-{key_prefix}",
                )

        result = await future
        log.debug("embed_one resolved key=%s dim=%d", key_prefix, len(result))
        return result

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts concurrently through the shared queue."""
        if not texts:
            log.debug("embed_batch called with empty list — skipping")
            return []

        log.debug("embed_batch texts=%d", len(texts))
        results = list(await asyncio.gather(*[self.embed_one(t) for t in texts]))
        log.debug("embed_batch completed texts=%d", len(texts))
        return results

    async def flush_and_close(self) -> None:
        """Flush any remaining items and stop the flush timer task."""
        pending_count = len(self._pending)
        log.info(
            "BatchEmbedder flush_and_close pending=%d flush_count=%d "
            "cache_hits=%d total_requests=%d provider_errors=%d",
            pending_count,
            self._flush_count,
            self._cache_hits,
            self._total_requests,
            self._provider_errors,
        )

        current = asyncio.current_task()
        if (
            self._flush_task
            and self._flush_task is not current
            and not self._flush_task.done()
        ):
            log.debug("flush_and_close cancelling pending flush_task")
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                log.debug("flush_and_close flush_task cancelled cleanly")

        if self._lock is not None:
            async with self._lock:
                if self._pending:
                    log.info(
                        "flush_and_close flushing remaining items count=%d",
                        len(self._pending),
                    )
                    await self._flush(trigger="shutdown")
        elif self._pending:
            # lock never initialised but pending items exist — should not happen
            log.error(
                "flush_and_close lock=None but pending=%d — items will be lost",
                len(self._pending),
            )
            self._futures_orphaned += len(self._pending)

        log.info("BatchEmbedder shutdown complete futures_orphaned=%d", self._futures_orphaned)

    def stats(self) -> dict:
        """Return observability snapshot. Safe to call from any context."""
        hit_rate = (
            round(self._cache_hits / self._total_requests, 3)
            if self._total_requests
            else 0.0
        )
        return {
            "total_requests": self._total_requests,
            "cache_hits": self._cache_hits,
            "cache_hit_rate": hit_rate,
            "cache_size": len(self._cache),
            "flush_count": self._flush_count,
            "provider_errors": self._provider_errors,
            "futures_orphaned": self._futures_orphaned,
            "pending": len(self._pending),
        }

    # ── internal ──────────────────────────────────────────────────────────────

    def _get_lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def _delayed_flush(self) -> None:
        log.debug("delayed_flush waiting window_ms=%g", self._window_s * 1000)
        await asyncio.sleep(self._window_s)
        async with self._get_lock():
            if self._pending:
                log.debug(
                    "delayed_flush window_expired pending=%d trigger=timeout",
                    len(self._pending),
                )
                await self._flush(trigger="timeout")
            else:
                log.debug("delayed_flush window_expired pending=0 nothing to flush")

    async def _flush(self, trigger: str = "unknown") -> None:
        if not self._pending:
            log.debug("_flush called with empty pending trigger=%s — skipping", trigger)
            return

        batch = self._pending[:]
        self._pending.clear()
        self._flush_count += 1
        flush_id = uuid4().hex[:8]

        # cancel the timer-based flush task if it was not the one that called us
        current = asyncio.current_task()
        if (
            self._flush_task
            and self._flush_task is not current
            and not self._flush_task.done()
        ):
            log.debug("_flush cancelling stale flush_task flush_id=%s", flush_id)
            self._flush_task.cancel()
        self._flush_task = None

        keys = [k for k, _, _ in batch]
        texts = [t for _, t, _ in batch]
        futures = [f for _, _, f in batch]

        log.info(
            "BatchEmbedder flush_start flush_id=%s trigger=%s batch_size=%d "
            "flush_count=%d",
            flush_id, trigger, len(batch), self._flush_count,
        )
        t0 = time.perf_counter()

        try:
            embeddings = await asyncio.to_thread(self._provider.embed, texts)
            duration_ms = round((time.perf_counter() - t0) * 1000)

            if len(embeddings) != len(batch):
                self._provider_errors += 1
                exc = ValueError(
                    f"Embedding response size mismatch: expected {len(batch)}, got {len(embeddings)}"
                )
                log.error(
                    "BatchEmbedder size_mismatch flush_id=%s expected=%d got=%d "
                    "provider=%s — setting exception on %d futures",
                    flush_id, len(batch), len(embeddings),
                    type(self._provider).__name__, len(futures),
                )
                for future in futures:
                    if not future.done():
                        future.set_exception(exc)
                    else:
                        log.warning(
                            "BatchEmbedder future already done flush_id=%s — skipping set_exception",
                            flush_id,
                        )
                return

            resolved = 0
            for key, embedding, future in zip(keys, embeddings, futures):
                self._cache_put(key, embedding)
                if not future.done():
                    future.set_result(embedding)
                    resolved += 1
                else:
                    log.warning(
                        "BatchEmbedder future already done flush_id=%s key=%s — "
                        "likely cancelled by caller",
                        flush_id, key[:8],
                    )

            log.info(
                "BatchEmbedder flush_done flush_id=%s trigger=%s batch_size=%d "
                "resolved=%d duration_ms=%d cache_size=%d",
                flush_id, trigger, len(batch), resolved, duration_ms, len(self._cache),
            )

        except BaseException as exc:
            duration_ms = round((time.perf_counter() - t0) * 1000)
            is_cancel = isinstance(exc, asyncio.CancelledError)

            if is_cancel:
                # CancelledError: task was cancelled externally — propagate after cleanup
                log.warning(
                    "BatchEmbedder flush_cancelled flush_id=%s duration_ms=%d "
                    "pending_futures=%d — setting CancelledError on all futures",
                    flush_id, duration_ms, len(futures),
                )
            else:
                self._provider_errors += 1
                log.error(
                    "BatchEmbedder flush_error flush_id=%s trigger=%s "
                    "error_type=%s error=%s duration_ms=%d — "
                    "setting exception on %d futures",
                    flush_id, trigger,
                    type(exc).__name__, exc,
                    duration_ms, len(futures),
                )

            orphaned = 0
            for future in futures:
                if not future.done():
                    future.set_exception(exc)
                    orphaned += 1
                else:
                    log.warning(
                        "BatchEmbedder future already done during error path "
                        "flush_id=%s — skipping",
                        flush_id,
                    )

            self._futures_orphaned += orphaned

            if is_cancel:
                raise  # CancelledError must propagate so asyncio handles it correctly

    def _cache_get(self, key: str) -> list[float] | None:
        val = self._cache.get(key)
        if val is not None:
            self._cache.move_to_end(key)
        return val

    def _cache_put(self, key: str, embedding: list[float]) -> None:
        if len(self._cache) >= self._cache_size:
            evicted_key, _ = self._cache.popitem(last=False)
            log.debug(
                "BatchEmbedder cache_evict evicted_key=%s cache_size=%d",
                evicted_key[:8], self._cache_size,
            )
        self._cache[key] = embedding
        self._cache.move_to_end(key)
