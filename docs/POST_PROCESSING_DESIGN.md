# Post-Processing Architecture & AI Enhancement Design (Phase 2)

This document outlines the architecture for the Phase 2 AI post-processing layer in `podcast-ctl`, designed to run after transcription normalization.

---

## 1. Objectives

Raw transcriptions from Whisper or speech-to-text models often suffer from:
* Lack of speaker differentiation (single stream of text).
* Verbal fillers (*"um"*, *"like"*, *"you know"*), false starts, and run-on sentences.
* Lack of higher-level structure (chapters, timestamps, topic shifts, takeaways).

The post-processing layer enhances normalized `TranscriptResult` objects into publication-ready documents.

---

## 2. Pipeline Integration

```
  ┌─────────────────────────┐
  │ Normalized Transcript   │ (Intermediate JSON with timed segments)
  └────────────┬────────────┘
               │
               ▼
  ┌─────────────────────────────────────────────────────────────┐
  │                 AI Post-Processing Pipeline                 │
  │                                                             │
  │  1. Punctuation & Verbal Filler Cleanup                    │
  │     • Preserves verbatim meaning                            │
  │     • Strips disfluencies & fixes homophone speech errors   │
  │                                                             │
  │  2. Contextual Diarization                                  │
  │     • Infers speaker changes and host/guest identities      │
  │     • Tags segments with verified speaker labels            │
  │                                                             │
  │  3. Chaptering & Topic Segmentation                         │
  │     • Identifies semantic shifts                            │
  │     • Generates timestamped chapter markers                 │
  │                                                             │
  │  4. Executive Summary & Show Notes                          │
  │     • Key takeaways, guest mentions, action items           │
  └────────────────────────────┬────────────────────────────────┘
                               │
                               ▼
  ┌─────────────────────────────────────────────────────────────┐
  │                    Enhanced Transcript                      │
  └─────────────────────────────────────────────────────────────┘
```

---

## 3. Supported AI Providers

A pluggable interface allows users to choose between local zero-cost models and cloud APIs:

| Provider | Type | Recommended Models | Use Case |
| :--- | :--- | :--- | :--- |
| **Ollama** | Local (Free) | `llama3.1:8b`, `qwen2.5:7b`, `mistral:7b` | Offline, zero-cost processing on Apple Silicon / GPU. |
| **Groq** | Cloud (Fast) | `llama-3.3-70b-versatile`, `mixtral-8x7b-32768` | Ultra-fast token generation at fraction of a cent. |
| **OpenAI** | Cloud | `gpt-4o-mini`, `gpt-4o` | High accuracy structured extraction. |
| **Anthropic** | Cloud | `claude-3-5-haiku`, `claude-3-5-sonnet` | Long-context podcast processing (up to 200k tokens). |

---

## 4. Chunking & Sliding Window Strategy

Podcasts are often 1–3 hours long (20,000–60,000 words), which exceeds single-pass prompt optimization.
* **Map Phase:** Transcripts are chunked into 15-minute overlapping sliding windows for segment-level cleanup and speaker attribution.
* **Reduce Phase:** Aggregated segment summaries are passed to a single global prompt to generate chapter markers, timeline table of contents, and executive summary.

---

## 5. Extensibility Interface

```python
from abc import ABC, abstractmethod
from podcast_ctl.models.transcript import TranscriptResult

class BasePostProcessor(ABC):
    @abstractmethod
    async def process(self, transcript: TranscriptResult) -> TranscriptResult:
        """Enhance transcript with cleaned text, speaker tags, chapters, or summaries."""
        pass
```
