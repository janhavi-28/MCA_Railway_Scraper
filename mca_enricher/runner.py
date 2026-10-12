"""
Batch runner v2 — processes MCA companies from start.

Features:
- Async worker pool with cooperative rate limiting
- Auto-checkpointing every 25 companies
- Resumability via CIN deduplication
- Graceful shutdown (Ctrl+C saves progress)
- tqdm progress bar
"""

import asyncio
import csv
import os
from pathlib import Path
from typing import List, Set, Dict, Any, Optional
import aiohttp
import pandas as pd
from tqdm import tqdm

from .config import (
    DEFAULT_INPUT_CSV,
    DEFAULT_OUTPUT_CSV,
    CHECKPOINT_INTERVAL,
    DEFAULT_CONCURRENCY,
    OUTPUT_COLUMNS,
    NOT_FOUND,
)
from .search import SearchEngine
from .enricher import CompanyEnricher
from .crawler import PlaywrightManager
from .logger import logger


class CheckpointWriter:
    """Thread-safe CSV checkpoint writer."""

    def __init__(self, output_path: str, interval: int = CHECKPOINT_INTERVAL):
        self.output_path = Path(output_path)
        self.interval    = interval
        self.buffer: List[Dict[str, str]] = []
        self._lock = asyncio.Lock()
        self._init_file()

    def _init_file(self):
        if not self.output_path.exists() or self.output_path.stat().st_size == 0:
            with open(self.output_path, "w", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS).writeheader()

    def get_processed_companies(self) -> Set[str]:
        """
        Return the set of company names already written.
        We use company name as the dedup key (since output has no CIN column).
        """
        done: Set[str] = set()
        if not self.output_path.exists():
            return done
        try:
            df = pd.read_csv(self.output_path, usecols=["Company"], dtype=str)
            for v in df["Company"].dropna():
                done.add(str(v).strip().upper())
        except Exception as e:
            logger.warning(f"Resume check error: {e}")
        return done

    async def add(self, result: Dict[str, str]):
        async with self._lock:
            self.buffer.append(result)
            if len(self.buffer) >= self.interval:
                self._flush()

    def flush(self):
        if self.buffer:
            self._flush()

    def _flush(self):
        if not self.buffer:
            return
        try:
            with open(self.output_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(
                    f, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore"
                )
                writer.writerows(self.buffer)
            logger.info(f"Checkpoint: {len(self.buffer)} rows saved -> {self.output_path.name}")
            self.buffer.clear()
        except Exception as e:
            logger.error(f"Checkpoint write error: {e}")


class BatchPipeline:
    """Full-dataset async enrichment pipeline."""

    def __init__(
        self,
        input_csv:   str            = DEFAULT_INPUT_CSV,
        output_csv:  str            = DEFAULT_OUTPUT_CSV,
        concurrency: int            = DEFAULT_CONCURRENCY,
        limit:       Optional[int]  = None,
    ):
        self.input_csv   = Path(input_csv)
        self.output_csv  = output_csv
        self.concurrency = concurrency
        self.limit       = limit
        self.writer      = CheckpointWriter(output_csv)
        self.search      = SearchEngine(request_delay=1.0)
        self.enricher    = CompanyEnricher(self.search)
        self._stop       = asyncio.Event()

    def _load(self) -> List[Dict[str, Any]]:
        if not self.input_csv.exists():
            raise FileNotFoundError(self.input_csv)

        df = pd.read_csv(self.input_csv, dtype=str)
        df.columns = df.columns.str.strip()

        if "Company Name" not in df.columns:
            raise ValueError(f"'Company Name' column missing. Found: {list(df.columns)}")

        done = self.writer.get_processed_companies()
        logger.info(f"Already processed: {len(done)} companies")

        pending: List[Dict[str, Any]] = []
        for row in df.to_dict(orient="records"):
            name = str(row.get("Company Name", "")).strip().upper()
            if name and name not in done:
                pending.append(row)

        if self.limit:
            pending = pending[: self.limit]

        logger.info(
            f"Input: {len(df)} total | Remaining: {len(pending)} | Processing: {len(pending)}"
        )
        return pending

    async def _worker(
        self,
        wid:     int,
        queue:   asyncio.Queue,
        session: aiohttp.ClientSession,
        pbar:    tqdm,
    ):
        while not self._stop.is_set():
            try:
                row = await asyncio.wait_for(queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                if queue.empty():
                    break
                continue
            try:
                res = await self.enricher.enrich(row, session)
                await self.writer.add(res)
            except Exception as e:
                logger.error(f"Worker {wid} error: {e}")
            finally:
                queue.task_done()
                pbar.update(1)

    async def run(self):
        pending = self._load()
        if not pending:
            logger.info("Nothing to process — all companies already done.")
            return

        queue: asyncio.Queue = asyncio.Queue()
        for item in pending:
            queue.put_nowait(item)

        pbar = tqdm(total=len(pending), desc="Enriching", unit="co")

        connector = aiohttp.TCPConnector(limit=self.concurrency * 3, ttl_dns_cache=300)
        async with aiohttp.ClientSession(connector=connector) as session:
            workers = [
                asyncio.create_task(self._worker(i, queue, session, pbar))
                for i in range(self.concurrency)
            ]
            try:
                await queue.join()
            except asyncio.CancelledError:
                logger.warning("Pipeline cancelled.")
            finally:
                self._stop.set()
                for w in workers:
                    w.cancel()
                await asyncio.gather(*workers, return_exceptions=True)
                pbar.close()
                self.writer.flush()
                await PlaywrightManager.close_browser()
                logger.info("Pipeline finished.")
