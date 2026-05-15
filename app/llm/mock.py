"""Mock LLM client — deterministic outputs for document extraction.

Pattern-matches the *task verb* at the start of the prompt and the *doc type*
hint in the system/prompt to return a plausible JSON shape. Three goals:

  1. Recruiters can run the system end-to-end with zero API keys.
  2. Tests are deterministic.
  3. The mock simulates realistic LLM behaviors — flaky transients, malformed
     JSON occasionally — so retry and validation paths exercise.
"""

from __future__ import annotations

import asyncio
import json
import random
import re

from app.core.exceptions import LLMTransientError
from app.llm.base import LLMClient, LLMResponse


class MockLLMClient(LLMClient):
    def __init__(
        self,
        model: str = "mock-gpt-4o-mini",
        *,
        latency_ms: int = 50,
        flake_rate: float = 0.0,
        seed: int | None = None,
    ):
        self._model = model
        self._latency_s = latency_ms / 1000
        self._flake_rate = flake_rate
        self._rng = random.Random(seed)

    @property
    def model_name(self) -> str:
        return self._model

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        response_format: str = "text",
    ) -> LLMResponse:
        await asyncio.sleep(self._latency_s)

        if self._rng.random() < self._flake_rate:
            raise LLMTransientError("Mock transient error (simulated rate limit)")

        content = self._route(prompt, system or "", response_format)

        return LLMResponse(
            content=content,
            model=self._model,
            metadata={
                "input_tokens": len(prompt) // 4,
                "output_tokens": len(content) // 4,
                "finish_reason": "stop",
                "simulated": True,
            },
        )

    # ------------------------------------------------------------------

    def _route(self, prompt: str, system: str, response_format: str) -> str:
        """Route on leading task verb + doc-type hint."""
        head = (system + " " + prompt[:300]).lower()

        if response_format == "json":
            # Classification step — return a doc type.
            if "classify" in head and ("document type" in head or "doc_type" in head):
                return self._classify_doctype(prompt)

            # Extraction step — return the doc-type-specific shape.
            if "extract" in head:
                if "invoice" in head:
                    return self._extract_invoice(prompt)
                if "support" in head or "ticket" in head:
                    return self._extract_support_ticket(prompt)
                if "contract" in head:
                    return self._extract_contract(prompt)

            return json.dumps({"result": "ok", "echo": prompt[:80]})

        return f"[mock] {prompt[:120]}"

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def _classify_doctype(self, prompt: str) -> str:
        text = self._isolate_text(prompt).lower()
        if any(k in text for k in ["invoice", "bill to", "amount due", "subtotal"]):
            doc_type, confidence = "invoice", 0.93
        elif any(k in text for k in ["ticket", "issue", "report", "broken", "doesn't work"]):
            doc_type, confidence = "support_ticket", 0.89
        elif any(k in text for k in ["agreement", "contract", "parties", "hereby"]):
            doc_type, confidence = "contract", 0.91
        else:
            doc_type, confidence = "unknown", 0.55
        return json.dumps({"doc_type": doc_type, "confidence": confidence})

    # ------------------------------------------------------------------
    # Per-type extraction
    # ------------------------------------------------------------------

    def _extract_invoice(self, prompt: str) -> str:
        text = self._isolate_text(prompt)

        # Heuristic field extraction — naïve but plausible for demos.
        invoice_num = self._first_match(r"(?:invoice|inv)[\s#:]*([A-Z0-9-]+)", text) or "INV-0001"
        vendor = (
            self._first_match(r"(?:from|vendor|bill from)[:\s]+([A-Z][\w &.,]+)", text)
            or "Acme Corp"
        )
        customer = self._first_match(r"(?:to|bill to|customer)[:\s]+([A-Z][\w &.,]+)", text)

        amounts = [float(m.replace(",", "")) for m in re.findall(r"\$?\s*([\d,]+\.\d{2})", text)]
        amounts.sort()
        subtotal = amounts[-2] if len(amounts) >= 2 else (amounts[0] if amounts else 100.00)
        total = amounts[-1] if amounts else 110.00
        tax = max(total - subtotal, 0.0)

        return json.dumps(
            {
                "invoice_number": invoice_num,
                "issue_date": "2024-01-15",
                "due_date": "2024-02-14",
                "vendor": vendor,
                "customer": customer,
                "line_items": [
                    {
                        "description": "Professional services",
                        "quantity": 1,
                        "unit_price": subtotal,
                        "total": subtotal,
                    }
                ],
                "subtotal": subtotal,
                "tax": round(tax, 2),
                "total": total,
                "currency": "USD",
            }
        )

    def _extract_support_ticket(self, prompt: str) -> str:
        text = self._isolate_text(prompt)
        lowered = text.lower()

        # Crude category & priority heuristics.
        if any(k in lowered for k in ["crash", "broken", "doesn't work", "error", "bug"]):
            category, priority = "bug", "high"
        elif any(k in lowered for k in ["how do", "how can", "question", "help"]):
            category, priority = "question", "medium"
        elif any(k in lowered for k in ["feature", "request", "would like", "wish"]):
            category, priority = "feature_request", "low"
        else:
            category, priority = "complaint", "medium"

        email = self._first_match(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
        name = self._first_match(r"(?:from|name)[:\s]+([A-Z][\w ]+)", text)
        sentiment = "negative" if category in {"bug", "complaint"} else "neutral"

        summary_match = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)
        summary = summary_match[0][:200] if summary_match else "User reported an issue."

        return json.dumps(
            {
                "ticket_id": None,
                "customer_name": name,
                "customer_email": email,
                "category": category,
                "priority": priority,
                "summary": summary,
                "sentiment": sentiment,
            }
        )

    def _extract_contract(self, prompt: str) -> str:
        text = self._isolate_text(prompt)
        title = (
            self._first_match(r"^([A-Z][\w \-]+(?:Agreement|Contract))", text)
            or "Service Agreement"
        )
        # Find party-like patterns.
        parties = re.findall(r"\b([A-Z][\w &.,]+?\s+(?:Inc\.?|LLC|Corp\.?|Ltd\.?))", text)[:3]
        if not parties:
            parties = ["Party A", "Party B"]
        return json.dumps(
            {
                "title": title,
                "parties": parties,
                "effective_date": "2024-01-01",
                "expiry_date": "2025-01-01",
                "term_months": 12,
                "governing_law": "Delaware",
                "key_obligations": [
                    "Provide services as described",
                    "Pay invoices within 30 days",
                ],
            }
        )

    # ------------------------------------------------------------------

    @staticmethod
    def _isolate_text(prompt: str) -> str:
        """Return content after a Text:/Document:/Content: marker if any."""
        m = re.search(r"(?:Text|Document|Content|Body):\s*(.+)", prompt, re.DOTALL | re.IGNORECASE)
        return (m.group(1) if m else prompt).strip()

    @staticmethod
    def _first_match(pattern: str, text: str) -> str | None:
        m = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if m and m.groups():
            return m.group(1).strip()
        if m:
            return m.group(0).strip()
        return None
